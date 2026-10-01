import json, collections, random, os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from remote_zip import read_member
OUT = "/Users/stefan/Dominion Labs/Lyric/test_data/music/humtrans/wav"
os.makedirs(OUT, exist_ok=True)
es = [e for e in json.load(open("/Users/stefan/Dominion Labs/Lyric/test_data/music/humtrans/entries.json")) if e["name"].endswith(".wav")]
split = json.load(open("/Users/stefan/Dominion Labs/Lyric/test_data/music/humtrans/train_valid_test_keys.json"))
where = {k: s for s, ks in split.items() for k in ks}
chosen = [e for e in es if where.get(e["name"].split("/")[-1][:-4]) in ("VALID", "TEST")]
train = collections.defaultdict(list)
for e in es:
    key = e["name"].split("/")[-1][:-4]
    if where.get(key) == "TRAIN":
        p, m, seg, rep = key.split("_")[:4]
        train[(m, seg)].append(e)
rng = random.Random(20260929)
for tune in rng.sample(sorted(train), 300):
    chosen.append(sorted(train[tune], key=lambda e: e["name"])[0])
def get(e):
    path = os.path.join(OUT, e["name"].split("/")[-1])
    if os.path.exists(path) and os.path.getsize(path) == e["usize"]:
        return 0
    for attempt in range(4):
        try:
            data = read_member(e)
            open(path, "wb").write(data)
            return len(data)
        except Exception as err:
            last = err
    print("FAILED", e["name"], last, flush=True)
    return 0
with ThreadPoolExecutor(8) as pool:
    done = 0
    for n, got in enumerate(pool.map(get, chosen), 1):
        done += got
        if n % 200 == 0:
            print(n, "of", len(chosen), round(done / 1e6), "MB", flush=True)
print("DONE", len(chosen), "files", round(done / 1e6), "MB", flush=True)
