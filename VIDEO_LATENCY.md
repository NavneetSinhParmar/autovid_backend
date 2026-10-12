# Local video thread measurements

The latest completed public video preview payload was rendered into isolated temporary files, without changing the stored jobs. Its output is 14.8 seconds, 1280x720, H.264 video with AAC audio. The same template, context, assets, preset `veryfast`, and CRF 22 were used.

Sequential measurements: one decoder/encoder/filter thread took 14.367 seconds; two took 8.933 seconds; three took 8.834 seconds. Two simultaneous renders with two threads each completed in 13.275 seconds total. Output metadata was validated for every render. This does not verify each layer visually or include upload, API submission, or download time.

Local `.env` and `.env.local` now use `FFMPEG_THREADS=2` and `FFMPEG_FILTER_THREADS=2`. Render concurrency remains two and memory admission remains enabled. Restart the backend to load these settings. Production settings remain at one thread until measured on the production machine.

Results are in `benchmark-video-threads-local.json`, `benchmark-video-pair-local.json`, and `benchmark-video-four-local.json`. Times depend on available RAM, CPU load, and template complexity; these are measurements, not latency guarantees.
