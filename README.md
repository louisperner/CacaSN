# CacaSN

[![ci](https://github.com/louisperner/CacaSN/actions/workflows/ci.yml/badge.svg)](https://github.com/louisperner/CacaSN/actions/workflows/ci.yml)

Supernova hunter for the public ZTF alert stream (via the [ALeRCE](https://alerce.science) broker),
with a check against the [Transient Name Server](https://www.wis-tns.org) so you only look at what
nobody has reported yet. *Português abaixo.*

## Install and run

    uv sync                         # or: pip install .
    uv run cacasn                   # candidates first detected in the last 21 days
    uv run cacasn --dias 3          # only the freshest
    uv run cacasn --fonte ztf --dias 120 --a-partir 30   # look back: first seen 30-120 days ago
    uv run cacasn --avisar          # alert for an unreported candidate with score >= 18
    open report.html

`python -m caca_sn` and `python3 cacasn.py` do the same. Python 3.9+; the only runtime dependency is
`structlog` (without it the program still runs, logging through the standard library).

With Docker:

    docker build -t cacasn .
    docker run --rm --env-file .env -v "$PWD/saida:/saida" cacasn --dias 2   # results land in ./saida

Each run writes `resultados.json`, `report.html` and one JSON line per event to `cacasn.log`, next to
the program or in `$CACASN_SAIDA` if set.
The desktop alert uses macOS `osascript`; elsewhere it goes to the log. Set `SENTRY_DSN`
(and `pip install ".[sentry]"`) to get scheduled-run failures in Sentry.

For each candidate the report shows the science · reference · difference stamps, the light curve,
a score, the reasons behind it, and whether the position is already on TNS.

## Rubin (LSST)

`--fonte rubin` (or the default `ambas`) also scans Rubin alerts through the [Fink](https://fink-broker.org)
broker: categories `most_likely_sn`, `sn_near_galaxy_candidate`, `extragalactic_new_candidate`,
`extragalactic_lt20mag_candidate` and `hostless_candidate`. Each object gets a score from Rubin's own
fields — brightness, S/N, `reliability`, point-likeness (`extendedness`), host with photometric
redshift, SuperNNova, positive flux, number of alerts, dipoles, and the **fraction of the flux that
is new** (difference vs. reference). Measured on 5,289 Rubin objects from 2026-06-25 to 07-20 against
what teams reported to TNS (93): **AUC 0.895** on a half not used to pick the weights (brightness
alone: 0.807). Professional teams report new sources; what is left over is mostly variability on an
existing source.

The top 30 are also checked against TNS, the VSX variable-star index and the ZTF history at that
position (many earlier ZTF detections = an old source), and get their full light curve from Fink.
A light curve longer than 60 days costs 5 points: every Rubin object reported to TNS in July spanned
≤ 18 days, while the unreported ones with 145–248 days (and up to 415 points, in the deep fields) were
sources that have varied for months. The report shows the brightening rate in mag/day per filter. In the July data this caught ASASSN-26de, a
dwarf nova that scored high and was not on TNS (dwarf novae go to VSX, not TNS).

**Stream status:** Fink, ALeRCE and ANTARES all show no Rubin alerts after mid-July 2026 (last night
2026-07-14 in Fink). CacaSN records this in `rubin_estado.json` and, when the stream comes back,
sends one "o Rubin voltou!" notification. Rubin's alarm threshold is 13.7 (top 1% of unreported
objects in July, ~2–3 per active night).

## Score

Up: SN probability from ALeRCE's stamp classifier and from its 2025 (beta) classifier, `drb`
(real/bogus network), detection on 2+ nights (an asteroid doesn't come back to the same spot),
both g and r filters, brightening within one filter.
Down: AGN probability (2025 classifier), single detection, "stellar" per ALeRCE, a Gaia star with
significant parallax or proper motion within 1.5" (a variable star), and a long detection history
at that position (an old source that varies, not a new explosion).

Measured on 97 candidates from 2026-10-13 to 23, 42 of which professional teams reported to TNS:

| Ranking by | AUC vs. "reported to TNS" |
|---|---|
| ALeRCE stamp classifier SN probability | 0.71 |
| ALeRCE 2025 (beta) classifier SN probability | 0.79 |
| CacaSN score | **0.96** |

The top 15 were all on TNS. Unreported candidates with high scores were AGN or variables on a
pre-existing source.

## TNS access (to check and to report)

1. Create an account at https://www.wis-tns.org (free; requests are reviewed by hand).
2. Create a bot at https://www.wis-tns.org/bots/edit and tick *Create new API key*.
3. Either set `TNS_BOT_ID`, `TNS_BOT_NAME`, `TNS_API_KEY` (see `.env.example`), or save `tns.json`
   next to `cacasn.py` (gitignored):

        {"bot_id": 12345, "bot_name": "your_bot_name", "api_key": "..."}

CacaSN first matches candidates locally against TNS's full public object list (~211k objects,
downloaded at most once a day into `cache/`, indexed by declination: 2,777 candidates in 0.8 s). The
API is used only to confirm "not on TNS" for candidates at the alarm score, because that file is
generated at 00:00 UTC. TNS allows 10 cone searches per minute; CacaSN does one every 6.5 s and honours the `429` reset header.
So the TNS check sets the pace: ~100 candidates take ~11 minutes, 500 take ~55. Without `tns.json`
the run takes seconds (and every candidate shows "TNS não consultado").

To report: `cacasn --rascunho <OID>` writes `rascunhos/<OID>.json`, an AT report in the TNS 2.0 bulk
format (`api/set/bulk-report`) with position, discovery date, the light curve as photometry and the
TNS IDs of the data source, camera and filters (read from objects already on TNS: ZTF = 48, ZTF-Cam =
196, g/r/i = 110/111/112; Rubin = 165, LSSTCam = 287, g/i/z = 161/163/164 — u/r/y = 160/162/165 are
inferred). It never sends anything: add `reporter` and `reporting_groupid` to `tns.json`, try it on
https://sandbox.wis-tns.org, then submit on TNS. Professional bots report clear ZTF supernovae within
hours, so speed matters: schedule `--avisar` every few hours.

Before reporting, `cacasn --ficha <OID>` runs the checks that used to be done by hand, all through
services outside the CDS (which takes SIMBAD and VizieR down when it is offline): TNS within 5", Gaia DR3
from the ESA archive (a source with parallax > 5 sigma means a star), known minor planets from SkyBoT at
the detection time, the host galaxy and its redshift from NED (absolute magnitude at the host distance),
and the last ZTF non-detection from ALeRCE (TNS rejects a report without it; the deepest limit of the
last night is used). It refuses with a single detection and warns when the source sits on the galaxy
nucleus (AGN/TDE risk). The draft then carries the non-detection and the host in the remarks.

`cacasn --enviar <OID>` shows that summary and sends the report through the TNS API only after you type
the OID to confirm (`--sandbox` for the test server); the TNS reply (AT name or errors) is printed and
logged, and the new AT is added to the follow-up list. Reporting through the API needs a TNS group:
create one, link your bot to it and put its ID in `reporting_groupid`. With `"aprovar_por_dialogo": true`
in `tns.json`, a scheduled `--avisar` run also opens a macOS dialog for each new ZTF candidate whose
check sheet is clean ("Depois" / "Enviar ao TNS"); nothing is sent without the click, and the dialog
closes by itself after 30 minutes.

## Following your discoveries

`cacasn --acompanhar 2026agsv` adds a TNS object to `acompanhar.json`. Every run then reads each
followed object from the TNS API and sends one notification when someone classifies it by spectrum
(e.g. "AT 2026agsv -> SN 2026agsv = SN Ia (z = 0.05)") — the same news as the AstroNotes emails,
without needing the mailbox.

## TNS news without the mailbox

Every run also downloads TNS's daily change file (`tns_public_objects_YYYYMMDD.csv.zip`, with your
bot) for each closed day since the last check, appends a summary to `novidades.md` (new transients,
every spectroscopic classification with type and redshift) and notifies only what matters: a
classification of an object CacaSN had seen, or a rare type (SLSN, TDE, kilonova, Ibn, IIn…). The daily
file only exists once the UTC day is over, so each run also asks the TNS search API for objects
classified since the previous run (`public_timestamp`): news reaches you within ~3 hours, and the same
object is never notified twice. On
2026-10-21..23 that was 330 new transients and 11 classifications, with two highlights.

## Dwarf novae

`cacasn --novas-anas` (and every `--avisar` run) hunts dwarf novae in outburst: ALeRCE light-curve
classifier CV/Nova candidates from the last 60 days, minus what is already in the TNS (local index, 3")
and in the VSX (one batch CDS X-Match, 5"). Each one left is measured from its ALeRCE light curve and
passes with >= 90% positive detections, amplitude >= 2 mag, >= 4 detections, <= 40 days and g-r <= 1.
A bright Gaia DR3 source within 1" flags it as "suspect". Output: `novas_anas.json` and
`novas_anas.html`; each object is notified once. If the X-Match fails, that run alerts nothing.
`--rascunho OID` also writes a TNS draft ("likely dwarf nova outburst"; pick type "Other" on the site).
Found 3 new ones on 2026-10-25 (AT 2026agtu/agtv/agtw).

## Development

    uv sync --all-extras
    uv run python -m unittest discover -s tests -t .   # offline, every API mocked
    uv run ruff check . && uv run mypy

Code layout: `caca_sn/avaliacao.py` (candidates and score), `catalogos.py` (Gaia, TNS),
`relatorio.py`, `alertas.py`, `rede.py` (HTTP with retries, atomic writes), `registro.py` (logging),
`cli.py`. See `CONTRIBUTING.md` and `CHANGELOG.md`.

`experimentos/fonte_previa.py` is an experiment (does a pre-existing source in the reference separate
reported from unreported? It didn't, AUC ~0.5); it needs `pip install ".[experimentos]"`.

---

## Português

Caçador de supernovas nos alertas públicos do ZTF via ALeRCE, conferindo no TNS o que já foi
reportado. Só biblioteca padrão do Python; o aviso usa notificação do macOS (em outros sistemas, imprime).

- `uv run cacasn [--dias 3] [--prob 0.5] [--avisar]` (ou `python3 cacasn.py`) gera `report.html`.
- `uv run cacasn --novas-anas` caça novas anãs em erupção (CV/Nova da ALeRCE fora do TNS e do VSX) e gera
  `novas_anas.html`; com `--avisar` isso roda junto a cada 3 h e avisa cada uma só uma vez.
- Para consultar e reportar no TNS: crie conta e um bot; use as variáveis do `.env.example` ou `tns.json`.
- `uv run cacasn --ficha OID` faz as checagens antes de reportar (TNS, Gaia da ESA, SkyBoT, NED e a última
  não-detecção); `uv run cacasn --enviar OID` mostra a ficha e envia pela API só depois de você digitar o
  OID (precisa de um grupo no TNS ligado ao bot, em `reporting_groupid`). Com `"aprovar_por_dialogo": true`
  no `tns.json`, o `--avisar` abre uma janela "Enviar ao TNS" para cada candidato novo com a ficha limpa.
- Quem reporta primeiro ao TNS fica como descobridor. Os robôs profissionais reportam as supernovas
  claras do ZTF em horas — a chance está em rodar com frequência e julgar os recortes.

## License

MIT — see `LICENSE`.
