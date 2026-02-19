

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
FCOPT_BASE = -80 -qopenmp -fpp
# -80 = Allow 80 column fixed format
# -qopenmp = Enable OpenMP directives
# -fpp = Enable Fortran preprocessor for #ifdef directives

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

# Select flags based on DEBUG setting
ifeq ($(DEBUG),1)
    FCOPT = $(FCOPT_BASE) $(FCOPT_DEBUG) -DDEBUG
    $(info *** DEBUG BUILD: Debug symbols, bounds checking, and tracebacks enabled ***)
else
    FCOPT = $(FCOPT_BASE) $(FCOPT_PROD)
endif

# Matrix-free mode disabled - causes NaN in PCG solver due to cumulative rounding errors
#FCOPT += -DMATRIX_FREE



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

