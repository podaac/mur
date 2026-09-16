# MATLAB Base Image for MUR Processing

This directory contains the base MATLAB image used by all MUR processing modules (iquam, l2p, landice, mrva).

## Purpose

Instead of each module downloading and installing the MATLAB Runtime separately, we create a base image with:
- MATLAB R2024b runtime installed at `/opt/matlabruntime/R2024b`
- Common runtime dependencies
- Standard MATLAB environment variables

This significantly reduces:
- Build time for individual modules
- Disk space usage
- Network bandwidth for repeated builds

## Building the Base Image

### Automated Build (Recommended)

You normally never build this image directly: `./build_module.sh <module>` (in the `mur/`
directory) builds it automatically if it's missing. To build or rebuild it on its own:

```bash
cd /path/to/mur
cp network.lic.example network.lic  # Edit with your license server details
./build_matlab_base.sh              # add --force to rebuild an existing image
```

### Manual Build (Advanced)

Only for a custom tag, external CI, or debugging this Dockerfile. The build context must be
the parent `mur` directory so `network.lic` is reachable:

```bash
cd /path/to/mur
cp network.lic.example network.lic  # Edit with your license server details
cd matlab-base
docker build --platform linux/amd64 -t mur-matlab-base:r2024b -f Dockerfile ..
```

## Usage

Each module's Dockerfile now starts with:

```dockerfile
FROM mur-matlab-base:r2024b AS matlab-runtime
# ... rest of module-specific build
```

## Image Size

- Full mathworks/matlab:r2024b image: ~15GB
- MATLAB Runtime only: ~3-4GB
- This base image: ~3.5GB (runtime + common dependencies)

## Updating MATLAB Version

To update to a newer MATLAB release:
1. Update the base image URL in this Dockerfile
2. Update the `FROM` tag in this Dockerfile
3. Rebuild the base image
4. Rebuild all module images

## Troubleshooting

If the base image build fails:
- Check network.lic has correct license server details
- Ensure license server is accessible
- Verify MATLAB download URL is still valid (check MathWorks downloads page)
