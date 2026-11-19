cwlVersion: v1.2
$graph:
- class: Workflow
  label: mur-cog
  doc: 'Cloud-optimized GeoTIFFs from a MUR L4 SST granule, for visualization. Reads
    one granule, writes one GeoTIFF per requested field, and writes the STAC metadata
    that publishes them: the catalog.json staged out alongside the rasters is ingested
    into dps-stac.maap-project.org and served by titiler-dps-stac.maap-project.org,
    so the layers are discoverable by date without a registration request or a public
    bucket.

    '
  id: mur-cog
  inputs:
    granule:
      doc: 's3:// href to one MUR L4 NetCDF granule, either the 1 km MUR-GLOB product
        or its MUR25-GLOB sibling.

        '
      label: L4 granule
      type: string
    fields:
      doc: 'Optional comma-separated subset of sst,anom,err,ice,mask. Empty picks
        a default from the product: sst,anom for the 1 km granule, where each field
        is ~400 MB compressed, and all five for MUR25, where they are trivial.

        '
      label: Fields
      type: string?
      default: ''
    stac-collection:
      doc: 'Optional. The collection id MAAP assigns at ingest, <username>__<algorithm>__<version>.
        Given it, each item gains map and preview links pointing at titiler. A container
        cannot work this out for itself -- the id is assigned after the job ends,
        and the registered algorithm name carries a suffix MAAP allocates -- so the
        orchestrator passes it or the links are left out.

        '
      label: Published STAC collection
      type: string?
      default: ''
    mode:
      doc: 'Optional "nrt" or "rea", recorded in the STAC item. The granule filename
        cannot supply it -- mode appears only in the directory (.../279nrt/...) --
        so it is inferred from the href when the href has that shape and omitted when
        it cannot be determined.

        '
      label: Analysis mode
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
        granule: granule
        fields: fields
        stac-collection: stac-collection
        mode: mode
      out:
      - outputs_result
- class: CommandLineTool
  id: main
  requirements:
    DockerRequirement:
      dockerPull: ghcr.io/podaac/mur/cog-dps:2.0.19
    NetworkAccess:
      networkAccess: true
    ResourceRequirement:
      outdirMax: 8192
  baseCommand: /opt/cog/bin/entrypoint.sh
  inputs:
    granule:
      type: string
      inputBinding:
        position: 1
        prefix: --granule
    fields:
      type: string?
      inputBinding:
        position: 2
        prefix: --fields
      default: ''
    stac-collection:
      type: string?
      inputBinding:
        position: 3
        prefix: --stac-collection
      default: ''
    mode:
      type: string?
      inputBinding:
        position: 4
        prefix: --mode
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
s:dateCreated: 2026-10-12
s:license: https://github.com/podaac/mur/blob/main/LICENSE
s:softwareVersion: 1.0.0
s:version: 2.0.19
s:releaseNotes: 'Split out of mrva, where it was briefly Stage 10b, so that the browse
  products do not depend on the heaviest stage in the pipeline. Now also emits a STAC
  catalog for MAAP to ingest, which is what makes the rasters addressable by date
  rather than by the job that produced them.

  '
s:keywords: MUR, SST, GHRSST, COG, visualization
$namespaces:
  s: https://schema.org/
$schemas:
- https://raw.githubusercontent.com/schemaorg/schemaorg/refs/heads/main/data/releases/9.0/schemaorg-current-http.rdf
