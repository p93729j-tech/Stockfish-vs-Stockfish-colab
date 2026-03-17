import pexpect, time, chess, chess.pgn, random, os
from datetime import datetime

pos = ""

ENGINE_PATHS = {"Engine A": "/content/stockfish/stockfish-ubuntu-x86-64-avx2", "Engine B": "/content/stockfish/stockfish-ubuntu-x86-64-avx2"}

def start_engine(p, n="Engine", c960=False, th=None, hz=None, tlim=600000):
    if not os.path.isfile(p): raise FileNotFoundError(f"Engine {p} não encontrado")
    e = pexpect.spawn(p, encoding="utf-8", timeout=tlim/1000+30)
    e.sendline("uci"); e.expect("uciok", 120)
    if c960:
        try: e.sendline("setoption name UCI_Chess960 value true")
        except Exception as ex: print(f"[{n}] WARNING: UCI_Chess960: {ex}")
    if th:
        try: e.sendline(f"setoption name Threads value {int(th)}")
        except Exception as ex: print(f"[{n}] WARNING: Threads: {ex}")
    if hz:
        try: e.sendline(f"setoption name Hash value {int(hz)}")
        except Exception as ex: print(f"[{n}] WARNING: Hash: {ex}")
    e.sendline("isready"); e.expect("readyok", 120)
    print(f"{n} iniciado e pronto."); return e

def prepare_engine_for_new_game(e, n="Engine"):
    try:
        e.sendline("ucinewgame")
        e.sendline("setoption name Clear Hash")
        e.sendline("isready")
        e.expect("readyok", 120)
    except Exception as ex: print(f"[{n}] WARNING: prepare: {ex}")

def get_engine_move_data(e, fen, dl, mt, n="Engine"):
    e.sendline(f"position fen {fen}"); e.sendline(f"go depth {dl} movetime {mt}")
    b = d = nd = 0; sc = sm = None
    t0 = time.monotonic(); timeout = t0 + mt/1000 + 5
    while time.monotonic() < timeout:
        try:
            l = e.readline().strip()
            if not l: continue
            if "info" in l:
                p = l.split()
                try:
                    for i, t in enumerate(p):
                        if t == "depth" and i+1 < len(p): d = int(p[i+1])
                        if t == "nodes" and i+1 < len(p): nd = int(p[i+1])
                        if t == "score" and i+2 < len(p):
                            st, sv = p[i+1], int(p[i+2])
                            if st == "cp": sc = sv/100.0; sm = None
                            else: sm = sv; sc = None
                except: pass
            if l.startswith("bestmove"):
                b = l.split()[1]; break
        except Exception as ex:
            print(f"[{n}] ERRO leitura: {ex}"); b = "resign"; break
    else:
        print(f"[{n}] timeout esperando bestmove"); b = "resign"
    eT = (time.monotonic() - t0) * 1000
    nps = nd / (eT/1000) if nd and eT > 0 else 0
    return b, d, nd, nps, sc, sm, eT

def _generate_chess960_board(seed=None):
    if seed is not None: random.seed(seed)
    try:
        i = random.randrange(960)
        try: return chess.Board.from_chess960_pos(i)
        except:
            try: return chess.Board(chess.chess960_starting_position(i))
            except: return chess.Board(chess.STARTING_FEN)
    except: return chess.Board(chess.STARTING_FEN)

def run_chess_match(n1, p1, n2, p2, c):
    print(f"===== {n1.upper()} vs {n2.upper()} =====")
    e1 = e2 = None
    if c.get("chess960", 0):
        b = _generate_chess960_board(c.get("seed")); print(f"Chess960 FEN: {b.fen()}")
    else:
        b = chess.Board(c.get("initial_fen", chess.STARTING_FEN))
    game = chess.pgn.Game()
    game.headers["Event"] = "Computer chess game"
    game.headers["Site"] = "?"
    game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
    game.headers["Round"] = "?"
    game.headers["White"] = n1
    game.headers["Black"] = n2
    game.headers["Result"] = "*"
    if b.fen() != chess.STARTING_FEN: game.headers["FEN"] = b.fen()
    node = game; mP = 0; r = "*"
    tlim = c.get("timelimit_ms", 600000)
    try:
        e1 = start_engine(p1, n1, c960=c.get("chess960",0), th=c.get("threads"), hz=c.get("hash_size"), tlim=tlim)
        e2 = start_engine(p2, n2, c960=c.get("chess960",0), th=c.get("threads"), hz=c.get("hash_size"), tlim=tlim)
        prepare_engine_for_new_game(e1, n1); prepare_engine_for_new_game(e2, n2)
        while not b.is_game_over() and mP < c.get("num_moves", 50):
            w = b.turn == chess.WHITE
            nm = n1 if w else n2
            pr = e1 if w else e2
            print(f"\n--- Turno {b.fullmove_number}: {'Brancas' if w else 'Pretas'} ({nm}) ---")
            print("Tabuleiro:\n", b)
            best, depth_found, nodes, nps, cp, mate, used_ms = get_engine_move_data(
                pr, b.fen(), c.get("depth", 18), c.get("movetime_ms", 5000), nm)
            if best == "(none)":
                r = b.result(claim_draw=True); break
            if cp is not None and cp <= -2.00:
                print(f"[{nm}] desiste (CP <= -2.00)"); r = "0-1" if w else "1-0"; break
            if not best or best == "resign":
                print(f"[{nm}] desistiu"); r = "0-1" if w else "1-0"; break
            try:
                mv = chess.Move.from_uci(best)
                if mv not in b.legal_moves: raise ValueError(f"ilegal: {best}")
                san = b.san(mv); b.push(mv); node = node.add_variation(mv)
            except Exception as ex:
                print(f"[{nm}] ERRO: {ex}"); r = "0-1" if w else "1-0"; break
            score_str = f"({cp:.2f} CP)" if cp is not None else (f"(Mate {mate})" if mate else "")
            depth_str = f", prof:{depth_found}" if depth_found else ""
            nps_str = f", NPS:{nps:,.0f}" if nps else ""
            print(f"[{nm}] jogou: {san} ({best}) {score_str}{depth_str}{nps_str}")
            print(f"tempo: {used_ms/1000:.1f}s")
            mP += 1
        if b.is_game_over() and r == "*": r = b.result()
        game.headers["Result"] = r
        print(f"\n===== PARTIDA ENCERRADA: {r} =====")
        print("\n--- PGN completo ---\n")
        print(game)
    except Exception as ex:
        print(f"\nERRO FATAL: {ex}"); import traceback; traceback.print_exc()
    finally:
        print("\nFinalizando engines...")
        for proc, name in ((e1, n1), (e2, n2)):
            if proc and proc.isalive():
                try: proc.sendline("quit"); proc.close(); print(f"{name} encerrado.")
                except: pass
            if proc and proc.isalive():
                try: proc.terminate()
                except: pass

if __name__ == "__main__":
    run_chess_match("Stockfish", ENGINE_PATHS["Engine A"],
                    "Stockfish", ENGINE_PATHS["Engine B"],
                    {
                        'chess960': 0, 'seed': None, 'hash_size': 564, 'threads': 1,
                        'depth': 18, 'movetime_ms': 1000, 'num_moves': 1000,
                        'initial_fen': pos
                    })
