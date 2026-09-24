cwlVersion: v1.2
$graph:
- class: Workflow
  label: mur-mrva
  doc: 'MUR multi-resolution variational analysis for one day. Fuses the per-sensor
    BIC files and iQuam in-situ observations against the seasonal climatology and
    the land/ice mask, emitting the GHRSST L4 MUR NetCDF granule, the MUR25 sibling
    product, and the coefficient file carried into the next day.

    '
  id: mur-mrva
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
    polar-cap-edge-file:
      doc: s3:// href to landice/CylinderP01_edge.bip under the static-resources root.
      label: Polar cap edge
      type: string
    seasonal-file:
      doc: 's3:// href to seasonal/mur_<doy>.nc for THIS day only (day 366 folds onto
        365). readSeasonal.m opens exactly one of the 365 files per run, which is
        why this is a single file rather than a staged directory -- a Directory input
        here would transfer the whole ~141 GB archive per job.

        '
      label: Seasonal climatology
      type: string
    landice-ice-p011-file:
      doc: 's3:// href to this day''s Global_ice_<YYYY>_<DDD>.bip.gz, from the same-run
        mur-landice job''s output.

        '
      label: Landice ice BIP (p011)
      type: string
    landice-grid-p01-file:
      doc: s3:// href to this day's landiceP01_<YYYY>_<DDD>.gds.gz from mur-landice.
      label: Landice grid (p01)
      type: string
    landice-icefiles-p011-file:
      doc: 's3:// href to this day''s icefiles_<YYYY>_<DDD>.txt from mur-landice.
        The file is real (written by landice/src/readosisafice.m''s write_file), but
        which output subdirectory it lands in on DPS is unconfirmed -- verify against
        one real landice job.

        '
      label: Landice icefiles listing (p011)
      type: string
    sensor-inputs-manifest:
      doc: 's3:// href to the unified BIC + IQUAM0 manifest JSON. Entries carry `sensor`
        and `relative_path` so localize_manifest reproduces the <SENSOR>/<YEAR>/<file>
        layout mrva4com_container.m''s per-sensor scan expects -- a layout a staged
        Directory could not express.

        '
      label: Sensor inputs manifest
      type: string
    sensors:
      doc: 'Optional comma-separated sensor list, e.g. "AMSR2R,MODISA". An empty string
        means all configured sensors.

        '
      label: Sensor subset
      type: string?
      default: ''
    mur25-grid-file:
      doc: 'Optional s3:// href to grids/MUR25grid.gds. An empty string skips MUR25
        product generation, which the entrypoint handles explicitly.

        '
      label: MUR25 grid
      type: string?
      default: ''
    prior-csp-file:
      doc: 'Optional s3:// href to the previous day''s coefficient file. An empty
        string means bootstrap instead of chaining from the previous day.

        '
      label: Prior-day coefficient
      type: string?
      default: ''
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
        polar-cap-edge-file: polar-cap-edge-file
        seasonal-file: seasonal-file
        landice-ice-p011-file: landice-ice-p011-file
        landice-grid-p01-file: landice-grid-p01-file
        landice-icefiles-p011-file: landice-icefiles-p011-file
        sensor-inputs-manifest: sensor-inputs-manifest
        sensors: sensors
        mur25-grid-file: mur25-grid-file
        prior-csp-file: prior-csp-file
      out:
      - outputs_result
- class: CommandLineTool
  id: main
  requirements:
    DockerRequirement:
      dockerPull: ghcr.io/podaac/mur/mrva-dps:2.0.0
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      outdirMax: 8192
  baseCommand: /opt/mrva/bin/entrypoint.sh
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
    polar-cap-edge-file:
      type: string
      inputBinding:
        position: 4
        prefix: --polar-cap-edge-file
    seasonal-file:
      type: string
      inputBinding:
        position: 5
        prefix: --seasonal-file
    landice-ice-p011-file:
      type: string
      inputBinding:
        position: 6
        prefix: --landice-ice-p011-file
    landice-grid-p01-file:
      type: string
      inputBinding:
        position: 7
        prefix: --landice-grid-p01-file
    landice-icefiles-p011-file:
      type: string
      inputBinding:
        position: 8
        prefix: --landice-icefiles-p011-file
    sensor-inputs-manifest:
      type: string
      inputBinding:
        position: 9
        prefix: --sensor-inputs-manifest
    sensors:
      type: string?
      inputBinding:
        position: 10
        prefix: --sensors
      default: ''
    mur25-grid-file:
      type: string?
      inputBinding:
        position: 11
        prefix: --mur25-grid-file
      default: ''
    prior-csp-file:
      type: string?
      inputBinding:
        position: 12
        prefix: --prior-csp-file
      default: ''
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
s:releaseNotes: 'First MAAP OGC application package for mrva. Requires the stage-out
  change redirecting the compiled-in /data/output/{csp,netcdf} paths. --l4-reference-root
  is deliberately omitted: it names a directory tree and localize.sh has no recursive
  S3 fetch.

  '
s:keywords: MUR, SST, GHRSST, L4, variational analysis
$namespaces:
  s: https://schema.org/
$schemas:
- https://raw.githubusercontent.com/schemaorg/schemaorg/refs/heads/main/data/releases/9.0/schemaorg-current-http.rdf
