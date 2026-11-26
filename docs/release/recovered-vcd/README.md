# Supplemental waveform copies

This directory restores eleven UART waveform files omitted from the original
release bundle. Each file is byte-identical to the SHA-256 and byte count already
recorded in that bundle's `../inputs.json`. Recovery used retained copies; it did
not rerun a simulation or change any sealed report, input, result, or execution
identity. Local recovery locations are deliberately not published.

`index.json` contains download metadata only. Its paths are relative to
`docs/release/`. The field `original_manifest_path` matches the exact value of
`../inputs.json[*].original_path`; it is not a local recovery path. The validator
also checks the upstream raw report, test, seed, variant, execution command,
transcript, build-time source snapshot, recorded binary identity, and expected
waveform SHA before offering a link. These checks validate execution records;
they do not require the original Linux executable to remain available.

The eleven entries cover the original failed parity, framing, byte-error
association, and interrupt requirement runs. The association test at seed 1 was
already bundled as `../inputs/164_waves.vcd`, so it is not duplicated here.
Together these provide waveform bytes for all twelve upstream requirement
failures. They do not provide waveforms for checker mutations or missing APB
protocol seeds, and they do not change the raw FAIL classifications.

To validate the supplement from the repository root:

```console
python -c "import sys; from pathlib import Path; sys.path.insert(0, 'py'); from recovered_waveforms import recovered_wave_links; links = recovered_wave_links(Path('docs/release'), Path('docs')); print('Verified supplemental waveforms:', len(links))"
```
