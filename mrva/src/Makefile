

SRC = /home/tmchin/cyc4  # used by "syncme" only.
CWD = $(PWD)             # used by "syncme" only.



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
FCOPT = -80 -qopenmp -pad -ipo -O3 -no-prec-div -fp-model fast=2 -xHost
# -pad, -Qpad = Enables the changing of the variable and array memory layout.
# -qopenmp, -Qopenmp = Enables OpenMP directives.



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

