# reddit-vulva-harvest

One-off, read-only dataset builder. Used to assemble an offline image dataset for
fine-tuning a Qwen-Image-Edit LoRA.

Runs locally on macOS. Python 3, standard library only. No PRAW, no framework, no hosting.

## API surface

Read-only GETs, two shapes:

- `/r/{sub}/top?t=all&limit=100&raw_json=1`
- `/r/{sub}/search?q={q}&restrict_sr=1&sort=top&t=all&limit=100&raw_json=1`

The second is used for five framing queries only ("from below", "legs up", "from above",
"top view", "squatting") to cover camera angles that a top-of-all-time listing misses.

Fields read from the response: `id`, `permalink`, `is_gallery`, `media_metadata`,
`preview.images[0].source` (url, width, height), `url_overridden_by_dest`. Everything else
is ignored.

**Writes: none.** Strictly GET.

Image bytes are fetched from `i.redd.it` / `preview.redd.it` directly, outside the API.

## Volume

20 listing calls at 100 items each. Single pass. No scheduler, no daemon, no webhook.

## Filtering

A candidate is kept only if its short side is >= 1100 px and its aspect ratio is <= 2.6.
Everything else is discarded.

## Output

A flat directory of image files, plus `sources.tsv` mapping each filename to the permalink
of the post it came from.

## Subreddits

GodPussy, Innies, LabiaGW, vulva, pussy, grool, creampies, Cummypussy, squirting, gape,
clitgonewild, assholegonewild, gonwild, pelfie

All NSFW. The search queries run against r/vulva and r/pussy, both already listed.

## Auth

Credentials are read from the environment, so no secrets are committed:

    export REDDIT_CLIENT_ID=...
    export REDDIT_CLIENT_SECRET=...

OAuth (`client_credentials`, script app) is used when credentials are present. Without them
the script falls back to unauthenticated access with host rotation and retries.

## Usage

    python3 harvest.py --dry-run          # list what would be downloaded
    python3 harvest.py                    # download
    python3 harvest.py --only vulva,pussy # subset

Output directory defaults to `~/Desktop/vulva_offcommons`.
