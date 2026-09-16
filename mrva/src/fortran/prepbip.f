! prepbip.f
! trims bip file by removing outliers etc
! removes intersensor bias from the trimmed bip file

! NOT PORTABLE due to ifort routines "ifport" and "system",
! but these should be easily adustable in many compilors.

! mike chin, 11.1.24

      program prepbip

      use filemod
      use spmm

      use ifport  ! for the ifort "system" call (used only once).


      ! parameters:
      integer maxbip
      parameter(maxbip=50)         ! max number of bip data files.


      ! spm data:
      type(cspmm) :: csp,dsp,bsp
      type(bip) :: bd, bnew


      real :: ref,rms,bias
      real :: wgtcutoff,multiplier
      character*128 :: mrvacmd, mrvaout


      ! name list variables:
      integer nbipfile  ! number of data files.
      integer Lbias     ! scale of inter-sensor bias analysis, bsp(:).
      character*128 :: bipfile(3,maxbip),reffile,stdfile,filename

      namelist /input/ nbipfile,bipfile,reffile,stdfile,Lbias


!
! input parameters from namelist file:
!
      open(7,file='prepbip.nml',form='formatted',status='old')
      read(7,nml=input)
      close(7)



!
! read reference and RMS coefficients:
!

      print*,'reading ',trim(reffile)
      call readcspmm(iosref,csp,trim(reffile))
      if(iosref>0) then
        print*,'prepbip: reference coefficient file not found'
        print*,'  ... aborting prepbip.'
        stop
      end if

      print*,'reading ',trim(stdfile)
      call readcspmm(iosrms,dsp,trim(stdfile))
      if(iosrms>0) then
        print*,'prepbip: tolerance coefficient file not found'
        print*,'  ... setting tolerance to 1 degree.'
      end if


!      
! trim each data file:
!


      do m=1,nbipfile

        read(bipfile(1,m),*) multiplier
        read(bipfile(2,m),*) wgtcutoff
        filename=trim(bipfile(3,m))


        !
        ! read data file:

        print*,' '
        print*,'prepbip.f: reading ',trim(filename)
        print*,'... multiplier=',multiplier,'wgtcutoff=',wgtcutoff
        call readbip(bd,trim(filename))
        call printstat(bd)


        !      
        ! mark outliers:

        if(multiplier>0) then

          do n=1,bd%n

            !call spmPoint(1,1,csp,bd%x(n),bd%y(n),0,0,0.,0.,ref)
            call samplecspmm(csp,bd%x(n),bd%y(n),ref)

            if(iosrms>0) then
              rms=1.0
            else
              !call spmPoint(1,1,dsp,bd%x(n),bd%y(n),0,0,0.,0.,rms)
              call samplecspmm(dsp,bd%x(n),bd%y(n),rms)
            end if

            if( abs(bd%sst(n)-ref) > rms*multiplier ) bd%err(n)=0.

          end do

        end if  ! multiplier>0.

      
        !
        ! trim output:

        allocate(bnew%x(1:bd%n))
        allocate(bnew%y(1:bd%n))
        allocate(bnew%t(1:bd%n))
        allocate(bnew%sst(1:bd%n))
        allocate(bnew%err(1:bd%n))

        next=0
        do n=1,bd%n
          if( bd%err(n) .gt. wgtcutoff ) then
            next = next + 1
            bnew%x(next)=bd%x(n)
            bnew%y(next)=bd%y(n)
            bnew%t(next)=bd%t(n)
            bnew%sst(next)=bd%sst(n)
            bnew%err(next)=bd%err(n)
          end if
        end do 
        bnew%n=next

        print*,bd%n,' points reduced to ',bnew%n,' points.'


        !
        ! correct sensor bias:
        if(.true.) then


          !
          ! sensor bias data:

          do n=1,bnew%n

            !call spmPoint(1,1,csp,bnew%x(n),bnew%y(n),0,0,0.,0.,ref)
            call samplecspmm(csp,bnew%x(n),bnew%y(n),ref)
            bd%sst(n)=bnew%sst(n)  ! save the original here.
            bnew%sst(n)=bnew%sst(n)-ref

          end do

          call writebiq(bnew,'prepbip_sensorbias.biq')


          !
          ! interpolate sensor bias:


            ! write "mrva.nml":
            open(8,file='mrva.nml',form='formatted',status='unknown')
            write(8,'(" $input")')
            write(8,'("lonmin=-180.0",/,"lonmax= 180.0")')
            write(8,'("latmin=-90.0",/,"latmax= 90.0")')
            write(8,'("L0=",i0,/,"LF=",i0)') Lbias,Lbias
            write(8,'("decay=",/,"  48.,48.,48.,48.,")')
            write(8,'("  36.,36.,36.,36.,",/,"  24.,24.,12.,06.,")')
            write(8,'("bgfile=","'' ''")')
            write(8,'("coefile=","'' ''")')
            write(8,'("nbipfile=",i0)'), 1
            write(8,'("bipfile=")')
            write(8,'("''",i0,"'',''",i0,"'',''",a,"'',")')
     &              Lbias,Lbias,"prepbip_sensorbias.biq"
            write(8,'(" $end")')
            close(8)

            ! run "mrva":
            write(mrvacmd,'("mrva > log.prepbip",i0)') m 
            icode = system( trim(mrvacmd) )  !!! compilor (ifort) specific !!!
            if(icode/=0) then
              print*,'prepbip: mrva run failed.'
              print*,'  ... aborting prepbip.'
              stop
            end if

            ! read mrva result into bsp:
            write(mrvaout,'("mrva.c",i2.2)') Lbias
            call readcspmm(iosref,bsp,trim(mrvaout))
            if(iosref>0) then
              print*,'prepbip: bias coefficient file not found'
              print*,'  ... aborting prepbip.'
              stop
            end if


          !
          ! subtract sensor bias:

          do n=1,bnew%n
            !call spmPoint(1,1,bsp,bnew%x(n),bnew%y(n),0,0,0.,0.,bias)
            call samplecspmm(bsp,bnew%x(n),bnew%y(n),bias)
            bnew%sst(n)=bd%sst(n)-bias
            bd%sst(n)=bias
          end do

          print*,'  ... Bias: ',sum(bd%sst(1:bnew%n))/bnew%n,
     &               minval(bd%sst(1:bnew%n)),maxval(bd%sst(1:bnew%n))


          deallocate(bsp%csp)

        end if ! sensor bias correction.



        !      
        ! re-write bip file:

        call printstat(bnew)

        call writebiq(bnew,trim(filename))


        deallocate(bnew%x,bnew%y,bnew%t,bnew%sst,bnew%err)
        deallocate(bd%x,bd%y,bd%t,bd%sst,bd%err)

      end do

      end program


!!!!!!!!!!

      subroutine printstat(b)
      use filemod
      type(bip) :: b

      m=b%n
        if(m>0) then
          print*,'  ... Box: ',minval(b%x(1:m)),maxval(b%x(1:m)),
     &                         minval(b%y(1:m)),maxval(b%y(1:m))
          print*,'  ... Time: ',minval(b%t(1:m)),maxval(b%t(1:m))
          print*,'  ... SST: ',sum(b%sst(1:m))/m,
     &                       minval(b%sst(1:m)),maxval(b%sst(1:m))
          print*,'  ... ERR: ',sum(b%err(1:m))/m,
     &                       minval(b%err(1:m)),maxval(b%err(1:m))
        end if
      end subroutine
!!!!!!!!!!
