cwlVersion: v1.2
$graph:
- class: Workflow
  label: mur-iquam
  doc: 'MUR in-situ buoy (iQuam) preprocessing. Downloads the monthly NOAA STAR iQuam
    NetCDF covering the requested window and writes one Global_IQUAM0_YYYY_DDD.bii
    per day across +/- buoy-day-range around the target day, for MRVA''s in-situ fan-in.

    '
  id: mur-iquam
  inputs:
    year:
      doc: Four-digit analysis year.
      label: Year
      type: string
    doy:
      doc: Day of year, 1-366.
      label: Day of year
      type: string
    mode:
      doc: nrt (interim) or rea (final).
      label: Processing mode
      type: string
    reference-date:
      doc: 'YYYY-MM-DD date this run treats as "today", for stability and future-date
        checks. Supplied by the orchestrator so it is never derived inside the container,
        which keeps historical reprocessing reproducible.

        '
      label: Reference date
      type: string
    buoy-day-range:
      doc: 'Half-width in days of the window processed around --doy. Must match mrva.sensors.IQUAM0.day_range
        (3) or MRVA''s fan-in manifest will reference days this job never wrote.

        '
      label: Buoy day range
      type: string
    stability-latency:
      doc: Days after which a day is considered stable and not rewritten.
      label: Stability latency
      type: string
  outputs:
    output:
      type: Directory
      outputSource: process/outputs_result
  steps:
    process:
      run: '#main'
      in:
        year: year
        doy: doy
        mode: mode
        reference-date: reference-date
        buoy-day-range: buoy-day-range
        stability-latency: stability-latency
      out:
      - outputs_result
- class: CommandLineTool
  id: main
  requirements:
    DockerRequirement:
      dockerPull: ghcr.io/podaac/mur/iquam-dps:2.0.0
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      ramMin: 4096
      coresMin: 1
      outdirMax: 1024
  baseCommand: /opt/iquam/bin/entrypoint.sh
  inputs:
    year:
      type: string
      inputBinding:
        position: 1
        prefix: --year
    doy:
      type: string
      inputBinding:
        position: 2
        prefix: --doy
    mode:
      type: string
      inputBinding:
        position: 3
        prefix: --mode
    reference-date:
      type: string
      inputBinding:
        position: 4
        prefix: --reference-date
    buoy-day-range:
      type: string
      inputBinding:
        position: 5
        prefix: --buoy-day-range
    stability-latency:
      type: string
      inputBinding:
        position: 6
        prefix: --stability-latency
  outputs:
    outputs_result:
      outputBinding:
        glob: ./output*
      type: Directory
s:author:
- class: s:Person
  s:name: JPL PO.DAAC MUR Team
s:contributor:
- class: s:Person
  s:name: JPL PO.DAAC MUR Team
s:citation: 'Chin, T.M., Vazquez-Cuervo, J., Armstrong, E.M. (2017). A multi-scale
  high-resolution analysis of global sea surface temperature. Remote Sensing of Environment,
  200, 154-169.

  '
s:codeRepository: https://github.com/podaac/mur
s:commitHash: null
s:dateCreated: 2026-09-17
s:license: https://github.com/podaac/mur/blob/main/LICENSE
s:softwareVersion: 1.0.0
s:version: 2.0.0
s:releaseNotes: 'First MAAP OGC application package for iquam. --work-dir/--log-dir/
  --output-dir became optional with runtime-relative defaults and are deliberately
  NOT exposed as job inputs.

  '
s:keywords: MUR, SST, in-situ, iQuam, buoy, GHRSST
$namespaces:
  s: https://schema.org/
$schemas:
- https://raw.githubusercontent.com/schemaorg/schemaorg/refs/heads/main/data/releases/9.0/schemaorg-current-http.rdf
