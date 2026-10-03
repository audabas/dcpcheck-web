# dcpcheck-web

An unofficial web UI for verifying Digital Cinema Packages with the
**[DCP-o-matic](https://dcpomatic.com) verifier**. It runs in Docker and was
written for a Synology NAS, but it runs on any machine that has Docker.

Point it at the folder where your DCPs live, and you get a page in your browser
that lists every DCP. You can start a verification with one click, follow its
progress and read the result: errors, Bv2.1 issues and warnings, as
reported by DCP-o-matic.

![dcpcheck showing a DCP with one error and one warning](docs/screenshot.png)

<sub>Screenshot made with sample data.</sub>

---

## All the real work is done by DCP-o-matic

dcpcheck is a thin layer on top of somebody else's remarkable work.
**Everything that matters here, the actual checking of a DCP, is done by
[DCP-o-matic](https://dcpomatic.com), written by Carl Hetherington** with
help from many contributors and translators.

DCP-o-matic is a free and open-source (GPL) program that makes, inspects,
plays and checks Digital Cinema Packages. For more than a decade, Carl has
built and maintained it, together with
libdcp, the library underneath it. That is a huge
amount of patient work on a field that is complex, poorly documented and
usually reserved for expensive commercial tools. Thanks to him, independent
filmmakers, festivals, small distributors, film schools and cinemas all over
the world can produce and check DCPs for free. The verifier used here reads
the ASSETMAP, PKL and CPLs, checks the hash of every file and looks inside
the pictures, sounds and subtitles. It also checks the DCP against the SMPTE
standards and the ISDCF Bv2.1 recommendations. dcpcheck only starts it and
shows what it says.

If this project is useful to you, DCP-o-matic is what you should thank:

- ❤️ **[Donate to DCP-o-matic](https://dcpomatic.com/donate)**. This is
  how the project lives.
- 📖 Read the [DCP-o-matic manual](https://dcpomatic.com/manual/html/), whose
  [chapter on verifying DCPs](https://dcpomatic.com/manual/html/ch19.html)
  explains what the verifier reports.
- 💬 Use the [DCP-o-matic forum](https://dcpomatic.com/forum/) for anything
  about DCPs and verification itself.

> dcpcheck is **not** affiliated with DCP-o-matic or its author. Please do
> not report problems with this web interface to DCP-o-matic. Open an issue
> here instead. If you think the verifier itself is wrong about a DCP, first
> check that DCP with DCP-o-matic's own verifier on a computer, then report it
> upstream.

---

## Features

- Finds every DCP (any folder containing an `ASSETMAP` or `ASSETMAP.xml`)
  under the mounted directory and its sub-folders, rescanning every 5
  minutes or on demand.
- Shows a summary of each DCP read from its CPL: type, standard
  (SMPTE/Interop), picture container, duration, sound and size.
- Sorts the list by name, size, status or date of last change.
- Runs `dcpomatic2_verify_cli` on demand, one DCP at a time (the others wait
  in a queue), with live progress and a Cancel button.
- Notices DCPs that are still being copied to the disk: while a folder keeps
  growing, it shows the copy's progress and speed instead of the Verify
  button, then verifies the DCP by itself once the copy is complete.
- Marks a DCP without errors as **OK**, with small flags for its Bv2.1
  issues and warnings.
- Sorts the notes into **Errors**, **Bv2.1 issues** and **Warnings**, with
  filters.
- Keeps the last result of each DCP, the verifier's full HTML report and its
  raw output.
- Mounts your DCPs **read-only**: dcpcheck never writes to them.
- Uses only the Python standard library besides DCP-o-matic: no database
  and no framework to keep up to date.

## Quick start

```sh
git clone https://github.com/audabas/dcpcheck-web.git
cd dcpcheck-web
# Edit docker-compose.yml: set the path of your DCP folder
docker compose up -d --build
```

Then open `http://<your-machine>:8080`.

Or, without compose:

```sh
docker build -t dcpcheck-web .
docker run -d --name dcpcheck -p 8080:8080 \
  -v /path/to/your/DCPs:/dcp:ro \
  -v dcpcheck-data:/data \
  --restart unless-stopped \
  dcpcheck-web
```

The build downloads the DCP-o-matic command-line package for Ubuntu 24.04
from dcpomatic.com (version 2.18.50 by default, see
[Build options](#build-options)).

## On a Synology NAS

This works on NAS models with an **x86-64** (Intel or AMD) processor, which
covers most "+" models. Check your model's CPU in Synology's spec sheets.
See [ARM](#arm) below for the others.

With **Container Manager** (DSM 7.2 and later):

1. Copy this repository to a shared folder on the NAS, for example
   `/volume1/docker/dcpcheck-web`. You can download it as a ZIP from GitHub.
2. In `docker-compose.yml`, set the left side of the `/dcp` volume to the
   folder holding your DCPs, for example `/volume1/DCP:/dcp:ro`.
3. Open **Container Manager → Project → Create**, choose that folder as the
   path and use the existing `docker-compose.yml`. Container Manager builds the
   image and starts the container.
4. Open `http://<nas-address>:8080`.

If you want the files in `data/` to belong to your DSM user instead of root,
uncomment `PUID`/`PGID` in `docker-compose.yml`. Run `id` over SSH to get your
values (often `1026` and `100`).

Verification reads every byte of the DCP to check its hashes, so its speed
depends on your disks. A feature can take 15 to 30 minutes on a typical NAS.
This is why verifications run one at a time.

## Configuration

Environment variables of the container:

| Variable         | Default                 | Meaning |
|------------------|-------------------------|---------|
| `DCP_ROOT`       | `/dcp`                  | Where the DCPs are mounted inside the container. |
| `DCP_ROOT_LABEL` | same as `DCP_ROOT`      | Name shown in the header for that directory (e.g. `/volume1/DCP`). |
| `SCAN_DEPTH`     | `3`                     | How many levels of sub-folders to search for DCPs. |
| `SCAN_INTERVAL`  | `300`                   | Seconds between automatic rescans (`0` to disable). |
| `MAX_PARALLEL`   | `1`                     | Number of verifications run at the same time. |
| `COPY_QUIET`     | `20`                    | Seconds without any change after which a folder being copied is considered complete. |
| `COPY_POLL`      | `3`                     | Seconds between two measures of a folder being copied (for its speed). |
| `AUTO_VERIFY`    | `1`                     | Verify a DCP by itself when its copy is complete. Set to `0` to turn it off. |
| `VERIFY_ARGS`    | *(empty)*               | Extra options for `dcpomatic2_verify_cli`, e.g. `--no-asset-hash-check`. Run `docker exec dcpcheck dcpomatic2_verify_cli --help` for the list. |
| `HTML_REPORT`    | `1`                     | Ask the verifier for its HTML report (`-o`). Set to `0` to turn it off. |
| `PUID` / `PGID`  | *(empty: root)*         | Run as this user/group. |
| `PORT`           | `8080`                  | Port the web server listens on inside the container. |
| `DATA_DIR`       | `/data`                 | Where results, logs and reports are kept. Mount a volume there. |

### Build options

| Build argument       | Default   | Meaning |
|----------------------|-----------|---------|
| `DCPOMATIC_VERSION`  | `2.18.50` | DCP-o-matic version to download. Look at [dcpomatic.com/download](https://dcpomatic.com/download) for the current one. |
| `DCPOMATIC_DL_ID`    | from the architecture | Package id on dcpomatic.com (`ubuntu-24.04-x86-cli` on amd64). |
| `DCPOMATIC_DEB_URL`  | *(empty)* | Full URL of a `.deb` to use instead. |

For example: `docker build --build-arg DCPOMATIC_VERSION=2.18.51 -t dcpcheck-web .`

If the NAS has no internet access, or the download fails, download the
**Ubuntu 24.04 CLI** package from
[dcpomatic.com/download](https://dcpomatic.com/download) yourself, put the
`.deb` in the [`deb/`](deb/) folder and build again. It is used instead of
the download.

### ARM

On arm64, the build tries the package id `ubuntu-24.04-arm-cli`. If
dcpomatic.com names its ARM package differently, pass the right id with
`--build-arg DCPOMATIC_DL_ID=...`, or put the `.deb` in `deb/`. 32-bit ARM
NAS models are not supported.

## Security

dcpcheck has **no authentication**. Anyone who can reach the port can see
your DCP names and start verifications, but cannot change, delete or download
your DCPs. Keep it on your local network. To reach it from outside, put it
behind a VPN or a reverse proxy with authentication, such as DSM's reverse
proxy with an access-control profile.

## How it works

- `app/dcpcheck/scanner.py` finds the DCP folders and reads their CPL.
- `app/dcpcheck/manager.py` keeps the queue and runs
  `dcpomatic2_verify_cli [VERIFY_ARGS] -o report.html <DCP>` for each
  verification.
- `app/dcpcheck/output.py` reads the verifier's output: stages, progress
  bar, and lines starting with `Error:`, `Bv2.1 error:` or `Warning:`.
- Results are stored in `/data/results.json`, with the raw output in
  `/data/logs/` and the verifier's HTML reports in `/data/reports/`.
- `app/static/` holds the single-page UI, in plain HTML, CSS and JavaScript.
  It loads its fonts from Google Fonts and falls back to system fonts when
  offline.

A DCP counts as being copied when its size, its size on disk or the newest
change time of its files moves between two measures, or when it was written
to just before it was found. dcpcheck then measures it every `COPY_POLL`
seconds until nothing changes for `COPY_QUIET` seconds. It counts the bytes
actually on disk, so that copies that give a file its final size before
writing it (Windows over SMB does) still show their progress. The percentage
compares them to the total size of the assets listed in the DCP's packing
list (PKL), so it only shows once the PKL has arrived.

When the copy is over, the verification starts by itself if dcpcheck saw
data arriving and the PKL says that everything is there. A copy that stopped
half-way, or a folder whose files only got new dates (after a change of
permissions, say), is left alone. A new DCP only appears at the next scan:
press *Rescan directory* to see it at once.

When a verification ends without any note and with a non-zero exit code,
dcpcheck shows it as *Verifier failed*. The raw output, a click away,
says why.

## Development

You don't need DCP-o-matic to work on the UI. A fake verifier prints the same
kind of output:

```sh
python3 dev/make_sample_dcps.py sample-dcps   # fake DCPs (sparse files, no disk used)
cd app
DCP_ROOT=../sample-dcps DATA_DIR=../data VERIFIER=../dev/fake_verify_cli.py \
  FAKE_SPEED=5 python3 -m dcpcheck
# open http://localhost:8080
```

To see how a copy in progress looks, make a fake DCP grow at 20 MB/s for 30
seconds (the bytes are real; add `--presize` to copy like Windows), then
rescan:

```sh
python3 dev/simulate_copy.py sample-dcps/Films/Arriving_FTR_2K_SMPTE_OV 20MB 30
```

Tests use only the standard library:

```sh
python3 -m unittest discover -s tests
```

## License

The code in this repository is released under the
[Licence Publique Rien À Branler](LICENSE) (LPRAB), the French version of
the WTFPL: *faites ce que vous voulez, j’en ai rien à branler*.

This license only covers dcpcheck itself. **DCP-o-matic is © Carl
Hetherington and contributors, licensed under the
[GNU GPL](https://www.gnu.org/licenses/)**. It is not included
in this repository. It is downloaded from dcpomatic.com when you build the
image, so an image you build contains DCP-o-matic under its own license. If
you redistribute such an image, the GPL's terms apply to that part.
