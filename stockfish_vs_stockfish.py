import pexpect, time, chess, random

ENGINE_PATHS = {"Engine A": "/content/stockfish/stockfish-ubuntu-x86-64-avx2", "Engine B": "/content/stockfish/stockfish-ubuntu-x86-64-avx2"}

def start_engine(path: str, name: str="Engine", chess960: bool=False, threads: int=None, hash_size:int=None, total_game_timelimit_ms: int=600000):
    pexpect_timeout = (total_game_timelimit_ms / 1000) + 30
    e = pexpect.spawn(path, encoding="utf-8", timeout=pexpect_timeout)
    e.sendline("uci"); e.expect("uciok", timeout=120)

    if chess960:
        try: e.sendline("setoption name UCI_Chess960 value true")
        except Exception as ex: print(f"[{name}] WARNING: Could not set UCI_Chess960 option: {ex}")

    if threads is not None:
        try: e.sendline(f"setoption name Threads value {int(threads)}")
        except Exception as ex: print(f"[{name}] WARNING: Could not set Threads option: {ex}")

    if hash_size is not None:
        try: e.sendline(f"setoption name Hash value {int(hash_size)}")
        except Exception as ex: print(f"[{name}] WARNING: Could not set Hash option: {ex}")

    e.sendline("isready"); e.expect("readyok", timeout=120)
    print(f"{name} iniciado e pronto.")
    return e

def prepare_engine_for_new_game(e, name="Engine"):
    try:
        e.sendline("ucinewgame")
        e.sendline("setoption name Clear Hash")
        e.sendline("isready")
        e.expect("readyok", timeout=120)
    except Exception as ex:
        print(f"[{name}] WARNING: Falha ao preparar nova partida: {ex}")

def get_engine_move_data(e, fen: str, depth_limit: int, movetime_ms: int, name="Engine"):
    e.sendline(f"position fen {fen}")
    e.sendline(f"go depth {depth_limit} movetime {movetime_ms}")

    best = None; depth = None; nodes = 0; score_cp = score_mate = None
    t0 = time.monotonic()

    while True:
        try:
            line = e.readline()
            if line == "":
                raise RuntimeError(f"[{name}] Engine não respondeu (EOF).")

            line = line.strip()
            if not line:
                continue

            if "info" in line:
                p = line.split()
                try:
                    if "depth" in p: depth = int(p[p.index("depth")+1])
                    if "nodes" in p: nodes = int(p[p.index("nodes")+1])
                    if "score" in p:
                        stype = p[p.index("score")+1]
                        sval = int(p[p.index("score")+2])
                        if stype == "cp":
                            score_cp = sval/100.0; score_mate = None
                        else:
                            score_mate = sval; score_cp = None
                except Exception as ex:
                    print(f"[{name}] WARNING: Erro ao analisar linha de informação: {ex}")

            if line.startswith("bestmove"):
                best = line.split()[1]
                break

        except Exception as ex:
            print(f"[{name}] ERRO ao ler saída da engine: {ex}")
            best = "resign"
            break

    elapsed_ms = (time.monotonic()-t0)*1000
    nps = nodes / (elapsed_ms/1000) if nodes and elapsed_ms>0 else 0
    return best, depth, nodes, nps, score_cp, score_mate, elapsed_ms

def _generate_chess960_board():
    try:
        idx = random.randrange(960)
        try:
            return chess.Board.from_chess960_pos(idx)
        except AttributeError:
            try:
                pos = chess.chess960_starting_position(idx)
                return chess.Board(pos)
            except Exception:
                return chess.Board(chess.STARTING_FEN)
    except Exception:
        return chess.Board(chess.STARTING_FEN)

def run_chess_match(n1,p1,n2,p2,config):
    print(f"===== INICIANDO PARTIDA ENTRE {n1.upper()} E {n2.upper()} ====")
    e1 = e2 = None

    if config.get("chess960", False):
        board = _generate_chess960_board()
        print(f"Posição inicial Chess960 (FEN): {board.fen()}")
    else:
        board = chess.Board(config.get("initial_fen", chess.STARTING_FEN))

    moves_played = 0; game_pgn = ""; result="*"
    total_game_timelimit_for_engine_init_ms = config.get("timelimit_ms",600000)

    try:
        e1 = start_engine(p1, n1,
                          chess960=config.get("chess960", False),
                          threads=config.get("threads"),
                          hash_size=config.get("hash_size"),
                          total_game_timelimit_ms=total_game_timelimit_for_engine_init_ms)

        e2 = start_engine(p2, n2,
                          chess960=config.get("chess960", False),
                          threads=config.get("threads"),
                          hash_size=config.get("hash_size"),
                          total_game_timelimit_ms=total_game_timelimit_for_engine_init_ms)

        prepare_engine_for_new_game(e1, n1)
        prepare_engine_for_new_game(e2, n2)

        while not board.is_game_over() and moves_played < config.get("num_moves",50):
            white = board.turn==chess.WHITE
            name = n1 if white else n2
            proc = e1 if white else e2

            print(f"\n--- Turno {board.fullmove_number}: {'Brancas' if white else 'Pretas'} ({name}) ---")
            print("Tabuleiro atual:\n", board)

            best, depth_found, nodes, nps, cp, mate, used_ms = get_engine_move_data(
                proc,
                board.fen(),
                config.get("depth", 18),
                config.get("movetime_ms", 5000),
                name
            )

            # Condição de desistência baseada em CP
            if cp is not None and cp <= -2.00:
                print(f"[{name}] desiste devido à avaliação desfavorável (<= -2.00 CP).")
                result = "0-1" if white else "1-0"
                break

            if not best or best=="resign":
                print(f"[{name}] desistiu ou não encontrou jogada.")
                result = "0-1" if white else "1-0"
                break

            try:
                mv = chess.Move.from_uci(best)
                if mv not in board.legal_moves:
                    raise ValueError(f"Jogada ilegal retornada: {best}")
                san = board.san(mv)
                board.push(mv)
            except Exception as ex:
                print(f"[{name}] ERRO: {ex}. Partida encerrada.")
                result = "0-1" if white else "1-0"
                break

            score_str = f"({cp:.2f} CP)" if cp is not None else (f"(Mate em {mate})" if mate is not None else "")
            depth_str = f", Profundidade: {depth_found}" if depth_found is not None else ""
            nps_str = f", NPS: {nps:,.0f}" if nps is not None else ""

            print(f"[{name}] jogou: {san} ({best}) {score_str}{depth_str}{nps_str}")
            print(f"Tempo gasto nesta jogada: {used_ms/1000:.1f}s")

            game_pgn += (f"{board.fullmove_number}. {san} " if white else f"{san} ")
            moves_played += 1

        if board.is_game_over() and result=="*":
            result = board.result()

        print(f"\n===== PARTIDA ENCERRADA!\nResultado final: {result}\nPGN da partida:\n\n{game_pgn.strip()}\n")

    except Exception as ex:
        print(f"\nERRO FATAL INESPERADO: {ex}")
        import traceback; traceback.print_exc()

    finally:
        print("\n--- Finalizando engines ---")
        for proc,name in ((e1,n1),(e2,n2)):
            if proc and proc.isalive():
                try:
                    proc.sendline("quit")
                    proc.close()
                    print(f"{name} encerrado.")
                except:
                    pass

if __name__=="__main__":
    match_config = {
        'chess960': False,
        'hash_size':256,
        'threads':1,
        'depth':18,
        'movetime_ms':1000,
        'num_moves':1000,
        'initial_fen': "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    }

    run_chess_match("Stockfish", ENGINE_PATHS["Engine A"], "Stockfish", ENGINE_PATHS["Engine B"], match_config)
