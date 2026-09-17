cwlVersion: v1.2
$graph:
- class: Workflow
  label: mur-landice
  doc: 'MUR land/sea/ice mask generation for one analysis day. Downloads OSI-SAF sea
    ice concentration from thredds.met.no and grids it onto the MUR 0.01-degree (p01)
    and 0.011-degree (p011) cylindrical grids, emitting the ice BIP, the ice-flagged
    land mask, and the icefiles listing for each resolution.

    '
  id: mur-landice
  inputs:
    year:
      doc: Four-digit analysis year, e.g. 2026.
      label: Year
      type: string
    doy:
      doc: Day of year, 1-366.
      label: Day of year
      type: string
    landmask-p01-file:
      doc: 's3:// href to grids/maskGLOBp01deg.gds under the static-resources root.
        Fetched inside the container by common/bin/localize.sh.

        '
      label: 0.01-degree land mask
      type: string
    gridindex-north-p01-file:
      doc: s3:// href to mat/p01/saf2north.mat.
      label: 0.01-degree NH OSI-SAF index
      type: string
    gridindex-south-p01-file:
      doc: s3:// href to mat/p01/saf2south.mat.
      label: 0.01-degree SH OSI-SAF index
      type: string
    landmask-p011-file:
      doc: s3:// href to grids/maskGlob1km.gds.
      label: 0.011-degree land mask
      type: string
    gridindex-north-p011-file:
      doc: s3:// href to mat/p011/saf2north.mat.
      label: 0.011-degree NH OSI-SAF index
      type: string
    gridindex-south-p011-file:
      doc: s3:// href to mat/p011/saf2south.mat.
      label: 0.011-degree SH OSI-SAF index
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
        landmask-p01-file: landmask-p01-file
        gridindex-north-p01-file: gridindex-north-p01-file
        gridindex-south-p01-file: gridindex-south-p01-file
        landmask-p011-file: landmask-p011-file
        gridindex-north-p011-file: gridindex-north-p011-file
        gridindex-south-p011-file: gridindex-south-p011-file
      out:
      - outputs_result
- class: CommandLineTool
  id: main
  requirements:
    DockerRequirement:
      dockerPull: ghcr.io/podaac/mur/landice-dps:2.0.0
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      ramMin: 6144
      coresMin: 2
      outdirMax: 2048
  baseCommand: /opt/landice/bin/entrypoint.sh
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
    landmask-p01-file:
      type: string
      inputBinding:
        position: 3
        prefix: --landmask-p01-file
    gridindex-north-p01-file:
      type: string
      inputBinding:
        position: 4
        prefix: --gridindex-north-p01-file
    gridindex-south-p01-file:
      type: string
      inputBinding:
        position: 5
        prefix: --gridindex-south-p01-file
    landmask-p011-file:
      type: string
      inputBinding:
        position: 6
        prefix: --landmask-p011-file
    gridindex-north-p011-file:
      type: string
      inputBinding:
        position: 7
        prefix: --gridindex-north-p011-file
    gridindex-south-p011-file:
      type: string
      inputBinding:
        position: 8
        prefix: --gridindex-south-p011-file
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
s:releaseNotes: 'First MAAP OGC application package for landice. Requires the MUR_OUTPUT_ROOT
  stage-out change: output now defaults to $PWD/output so CWL''s "glob: ./output*"
  can collect it.

  '
s:keywords: MUR, SST, sea ice, OSI-SAF, land mask, GHRSST
$namespaces:
  s: https://schema.org/
$schemas:
- https://raw.githubusercontent.com/schemaorg/schemaorg/refs/heads/main/data/releases/9.0/schemaorg-current-http.rdf
