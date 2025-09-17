
#FC = /usr/local/bin/g95
#FCOPT = -funroll-loops -O2

#FC = /usr/local/bin/gfortran
#FCOPT = -ffixed-line-length-none -O2

#FC = /usr/local/bin/ifort
#FCOPT = -80 -O2 -openmp
##FCOPT = -80 -O2

#FC = /usr/pgi/linux86/bin/pgf90
#FCOPT = -Mextend 

# Intel(R) Fortran Intel(R) 64 Compiler Version 19.0.4.243 Build 20190416
FC = /opt/intel/bin/ifort
FCOPT = -80 -qopenmp -pad -ipo -O3 -no-prec-div -fp-model fast=2 -xHost

LD = $(FC)
LDOPT = $(FCOPT)


#MOD = spmm.o filemod.o
MOD = spmm.o

#OBJ = spm.o
OBJ = $(MOD)


#default: cbscxdata cbscxcoeff move
default: cbscxdata cbscxcoeff cbscxcoeffvector move

cbscxdata: cbscxdata.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

cbscxcoeff: cbscxcoeff.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

cbscxcoeffvector: cbscxcoeffvector.f $(OBJ)
	$(FC) $(FCOPT) $@.f \
	$(OBJ) $(LIBNETCDF) -o $@

spmm.o: spmm.f
	$(FC) $(FCOPT) -c $< -o $@

#.f.o:
#	$(FC) $(FCOPT) -c $< -o $@


clean:
	rm -f *.o *.mod
	rm -f cbscxdata cbscxcoeff
	rm -f *.dat *.out *.nml

move:
	mv cbscxdata $$HOME/bin/
	mv cbscxcoeff $$HOME/bin/
	mv cbscxcoeffvector $$HOME/bin/

