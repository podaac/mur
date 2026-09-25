

SRC = /home/tmchin/cyc4  # used by "syncme" only.
CWD = $(PWD)             # used by "syncme" only.

# ========================================================================
# Build Mode Configuration
# ========================================================================
# DEBUG=1  - Enable debug symbols, bounds checking, and stack traces
# DEBUG=0  - Production build with full optimizations (default)
#
# Usage:
#   make DEBUG=1          # Debug build
#   make                  # Production build
#   make DEBUG=0          # Explicit production build
# ========================================================================
DEBUG ?= 0

#FC = /usr/pgi/linux86/bin/pgf90
#FCOPT = -Mextend

#FC = /usr/local/bin/g95
#FCOPT = -funroll-loops -O2


#FC = /bin/gfortran
##FC = /usr/bin/gfortran
#FCOPT = -ffixed-line-length-none -Ofast -fopenmp

# for new ifort:
FC = /opt/intel/bin/ifort
# Intel(R) Fortran Intel(R) 64 Compiler Version 19.0.4.243 Build 20190416

# Base flags (always used)
FCOPT_BASE = -80 -qopenmp -fpp -heap-arrays 64
# -80 = Allow 80 column fixed format
# -qopenmp = Enable OpenMP directives
# -fpp = Enable Fortran preprocessor for #ifdef directives
# -heap-arrays 64 = automatic arrays over 64 KB go on the heap, not the stack
#
# -heap-arrays is not a tuning flag here, it is what makes the solver run at
# all inside a container. The PCG solver declares automatic work arrays sized
# by the unknown count: at L=8 that is 2,115,612 REAL*8, or 16.1 MB, in a
# single array. DPS job 50f7b39a died on the first touch of one --
#
#   Starting PCG solver (maxIter= 2115612 )
#   forrtl: severe (174): SIGSEGV, segmentation fault occurred
#
# -- with the entrypoint reporting, a hundred lines earlier:
#
#   Warning: Could not set unlimited stack size
#   Stack:    10240 (soft limit)
#
# 10 MB of stack, 16.1 MB of array. The entrypoint asks for an unlimited stack
# and says so when refused, but inside DPS it IS refused: the hard limit comes
# from the Docker daemon, cwltool does not pass --ulimit, and the daemon is not
# ours. So the stack size is not something this project can set, and a solver
# that depends on it is a solver that runs on the developer's laptop and dies
# on the platform.
#
# The threshold keeps small temporaries on the stack, so the cost is confined
# to the few arrays that were the problem. ifort allocates these per-thread,
# which also covers the OpenMP workers -- they never saw `ulimit -s` anyway,
# only KMP_STACKSIZE, so they were one L-level away from the same crash.

# Production optimization flags
FCOPT_PROD = -pad -ipo -O3 -no-prec-div -fp-model fast=2 -xHost
# -pad = Enables changing of variable and array memory layout
# -ipo = Interprocedural optimization
# -O3 = Aggressive optimizations
# -no-prec-div = Faster division
# -fp-model fast=2 = Fast floating point model
# -xHost = Optimize for host CPU

# Debug flags for crash investigation
FCOPT_DEBUG = -g -traceback -check bounds -check uninit -fpe0 -warn all -O0
# -g = Generate debug symbols (enables line numbers in stack traces)
# -traceback = Generate stack trace on runtime errors
# -check bounds = Runtime array bounds checking (catches out-of-bounds access)
# -check uninit = Check for uninitialized variables
# -fpe0 = Stop on floating-point exceptions (div by zero, overflow, invalid)
# -warn all = Enable all compiler warnings
# -O0 = No optimization (makes debugging easier, variables not optimized away)

# infoMatrix storage precision. real*4 by default: 24.72 GiB rather than
# 49.43 at L=11, for a 30.77 GiB working set rather than 55.48. real*8 is the
# opt-out, and it is an opt-out rather than the default because it does not
# fit on any pool available to us -- see the comment block at the top of
# spmm.f, including the validation this has not had.
ifeq ($(INFOMATRIX_R8),1)
    FCOPT_BASE += -DINFOMATRIX_R8
    $(info *** infoMatrix in real*8: 55.48 GiB at L=11, needs >64 GiB ***)
else
    $(info *** infoMatrix in real*4 -- validate against production output ***)
endif

# Select flags based on DEBUG setting
ifeq ($(DEBUG),1)
    FCOPT = $(FCOPT_BASE) $(FCOPT_DEBUG) -DDEBUG
    $(info *** DEBUG BUILD: Debug symbols, bounds checking, and tracebacks enabled ***)
else
    FCOPT = $(FCOPT_BASE) $(FCOPT_PROD)
endif

# Matrix-free mode: explored but not pursued.
# Computed stencil coefficients on-the-fly instead of storing infoMatrix to reduce memory ~21x.
# Had NaN issues in PCG solver due to cumulative rounding errors.
# Code remains in spmm.f behind #ifdef MATRIX_FREE guards but is not built.
# See MATRIX_FREE_IMPLEMENTATION_NOTES.txt for details.



#FC = /usr/local/bin/ifort
##FCOPT = -80 -O2
##FCOPT = -80 -O2 -openmp -pad
##FCOPT = -80 -openmp -pad -fast -WB
#FCOPT = -80 -openmp -pad -fast



LD = $(FC)
LDOPT = $(FCOPT)


MOD = spmm.o filemod.o

#OBJ = spm.o
OBJ = $(MOD)


##default: syncme mrva spgrid matchup
##default: mrva spgrid trimbip
##default: mrva spgrid prepbip saf2bip
##default: mrva spgrid prepbip 
default: mrva samplegdscsp spgrid trimbip3 makehiresgrid

syncme:
	if test $(SRC) != $(CWD); then rsync -a $(SRC)/ $(CWD); fi

mrva: mrva.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

samplegdscsp: samplegdscsp.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

spgrid: spgrid.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

prepbip: prepbip.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

trimbip: trimbip.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

trimbip3: trimbip3.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

makehiresgrid: makehiresgrid.f
	$(FC) $(FCOPT) $@.f -o $@

saf2bip: 
	ln -sf ice/saf2north.mat .; \
	ln -sf ice/saf2south.mat .; \
	ln -sf ice/latlonOSISAFnh.mat .; \
	ln -sf ice/latlonOSISAFsh.mat .; \
	ln -sf ice/maskGlob1km.gds .; \
	ln -sf ice/readOSISAFnh.m .; \
	ln -sf ice/readOSISAFsh.m .; \
	ln -sf ice/saf2bip.m .

matchup: matchup.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

pathfinder: pathfinder.f
	$(FC) $(FCOPT) $@.f -o $@

testspm: testspm.o $(OBJ)
	$(LD) $(LDOPT) $@.o \
	$(OBJ) $(LIBNETCDF) -o $@

testspm.o: testspm.f testspm.h $(MOD)
	$(FC) $(FCOPT) -c $< -o $@

spm.o: spm.f spm.h
	$(FC) $(FCOPT) -c $< -o $@

spmm.o: spmm.f
	$(FC) $(FCOPT) -c $< -o $@

filemod.o: filemod.f
	$(FC) $(FCOPT) -c $< -o $@


#.f.o:
#	$(FC) $(FCOPT) -c $< -o $@


clean:
	rm -f *.o *.mod
	rm -f a.out testspm
	rm -f mrva fort.* mrva.c?? mrva.u??
	rm -f pathfinder
	rm -f spgrid
	rm -f trimbip trimbip3
	rm -f prepbip *.bip *.csp log.*
	rm -f bin2bip_head.nml
	rm -f saf2bip.m readOSISAF*.m latlonOSISAF*.mat saf2???th.mat
	rm -f   maskGlob1km.gds

