import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_sherpa import TEXTS, load_wav, make_sensevoice, run_offline

WAV = Path(__file__).resolve().parent / "wav"

rec = make_sensevoice()
for i in range(8):
    p = WAV / f"case_{i + 1}.wav"
    x = load_wav(p)
    hyp, secs = run_offline(rec, x)
    print(f"{p.name:12s} ref={TEXTS[i]!r:20s} hyp={hyp!r}  ({secs:.2f}s)")
