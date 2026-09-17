# Local data boundary

`data/` is intentionally ignored except for this file. It contains locally generated audio,
model artifacts, manifests, run records and formal decision history. Do not commit private
laboratory data, API responses containing secrets, or third-party datasets whose licences do
not allow redistribution.

Important trace files:

- `runs/<kind>/<run_id>.json`: durable background-run records.
- `denoised/denoise_runs_v2.csv`: fixed-schema denoise trace. Legacy
  `denoise_runs.csv` is preserved but no longer appended.
- `matrix/channel_runs_v2.csv`: set and measured SNR plus set and measured bitrate.
- `loop/listening_v1.jsonl`: blinded human A/B judgements.
- `loop/loop_status.json`: confirmed rounds only; temporary previews stay in memory.

For a wiring-only demo, run `python scripts/bootstrap_demo.py`. The generated tones and noises
are synthetic smoke fixtures, not scientific speech data and not evidence for model quality.
