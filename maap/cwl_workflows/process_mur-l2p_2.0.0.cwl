cwlVersion: v1.2
$graph:
- class: Workflow
  label: mur-l2p
  doc: 'MUR L2P-to-BIC conversion for one sensor and one data day. Reads the granule
    list from a manifest JSON, localizes every listed granule, bins the quality-screened
    observations onto the MUR grid, and emits Global_<SENSOR>_<YEAR>_<DOY>.bic plus
    its L2Plist text file.

    '
  id: mur-l2p
  inputs:
    sensor:
      doc: One of AMSR2R, MODISA, MODIST, AVMTAG, AVMTBG.
      label: Sensor
      type: string
    region:
      doc: Always 'Global' today.
      label: Region
      type: string
    year:
      doc: 'Four-digit year of the DATA day, which is not necessarily the analysis
        day -- each analysis day reprocesses a window of surrounding data days.

        '
      label: Year
      type: string
    doy:
      doc: Day of year of the data day, 1-366.
      label: Day of year
      type: string
    rewrite:
      doc: 0 = keep an existing BIC, 1 = overwrite it.
      label: Rewrite flag
      type: string
    granules-manifest:
      doc: 's3:// href to a manifest JSON of the form {"files": [{"path": "s3://..."}]}
        listing exactly this invocation''s L2P granules. Written per-invocation by
        run_mur_maap.py; the entries point at the workspace bucket rather than PO.DAAC,
        because localize.sh''s plain `aws s3 cp` cannot authenticate to a DAAC.

        '
      label: Granules manifest
      type: string
  outputs:
    output:
      type: Directory
      outputSource: process/outputs_result
  steps:
    process:
      run: '#main'
      in:
        sensor: sensor
        region: region
        year: year
        doy: doy
        rewrite: rewrite
        granules-manifest: granules-manifest
      out:
      - outputs_result
- class: CommandLineTool
  id: main
  requirements:
    DockerRequirement:
      dockerPull: ghcr.io/podaac/mur/l2p-dps:2.0.0
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      ramMin: 8192
      coresMin: 2
      outdirMax: 2048
  baseCommand: /opt/l2p/bin/entrypoint.sh
  inputs:
    sensor:
      type: string
      inputBinding:
        position: 1
        prefix: --sensor
    region:
      type: string
      inputBinding:
        position: 2
        prefix: --region
    year:
      type: string
      inputBinding:
        position: 3
        prefix: --year
    doy:
      type: string
      inputBinding:
        position: 4
        prefix: --doy
    rewrite:
      type: string
      inputBinding:
        position: 5
        prefix: --rewrite
    granules-manifest:
      type: string
      inputBinding:
        position: 6
        prefix: --granules-manifest
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
s:releaseNotes: 'First MAAP OGC application package for l2p. Granule fan-in arrives
  as a single manifest href rather than a CWL array or Directory -- see docs/input-contract.html
  section 3.

  '
s:keywords: MUR, SST, L2P, GHRSST, binning
$namespaces:
  s: https://schema.org/
$schemas:
- https://raw.githubusercontent.com/schemaorg/schemaorg/refs/heads/main/data/releases/9.0/schemaorg-current-http.rdf
