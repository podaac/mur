! trimbip.f
! trim bip file

      program trimbip

      use filemod
      use spmm


      ! parameters:
      integer maxbip
      parameter(maxbip=50)         ! max number of bip data files.


      ! spm data:
      real, allocatable:: csp(:),dsp(:)
      type(bip) :: bd, bnew

      real :: ref,rms


      ! input parametgers:
      character*128 :: bipfile(3,maxbip),reffile,stdfile,filename
      real :: wgtcutoff,multiplier

      integer nbipfile  ! number of data files.

      ! name list variables:
      namelist /input/ nbipfile,bipfile,reffile,stdfile,
     &                 multiplier,wgtcutoff


!
! input parameters from namelist file:
!
      open(7,file='trimbip.nml',form='formatted',status='old')
      read(7,nml=input)
      close(7)



!
! read reference and RMS coefficients:
!

      print*,'reading ',trim(reffile)
      !call readcoeffglobal(iosref,csp,trim(reffile))
      call readcoeff(iosref,csp,trim(reffile))
      if(iosref>0) then
        print*,'TRIMBIP: reference coefficient file not found'
        print*,'  ... aborting trimbip.'
        stop
      end if

      print*,'reading ',trim(stdfile)
      !call readcoeffglobal(iosrms,dsp,trim(stdfile))
      call readcoeff(iosrms,dsp,trim(stdfile))
      if(iosrms>0) then
        print*,'trimbip: tolerance coefficient file not found'
        print*,'  ... setting tolerance to 1 degree.'
      end if


!      
! trim each data file:
!


      do m=1,nbipfile

        read(bipfile(1,m),*) multiplier
        read(bipfile(2,m),*) wgtcutoff
        filename=trim(bipfile(3,m))

        if(multiplier>0) then

          !
          ! read data files:
          print*,'trimbip.f: reading ',trim(filename)
          print*,'... multiplier=',multiplier,'wgtcutoff=',wgtcutoff
          call readbip(bd,trim(filename))
          if(bd%n>0) then
            print*,'  ... box: ',minval(bd%x),maxval(bd%x),
     &                           minval(bd%y),maxval(bd%y)
            print*,'  ... time range: ',minval(bd%t),maxval(bd%t)
            print*,'  ... sst: ',sum(bd%sst)/bd%n,
     &                           minval(bd%sst),maxval(bd%sst)
            print*,'  ... err: ',sum(bd%err)/bd%n,
     &                           minval(bd%err),maxval(bd%err)
          end if


          !      
          ! mark outliers:


          do n=1,bd%n

            call spmPoint(1,1,csp,bd%x(n),bd%y(n),0,0,hx,hy,ref)

            if(iosrms>0) then
              rms=1.0
            else
              call spmPoint(1,1,dsp,bd%x(n),bd%y(n),0,0,hx,hy,rms)
            end if

            if( abs(bd%sst(n)-ref) > rms*multiplier ) bd%err(n)=0.

          end do


      
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
          ! re-write bip file:

          !call writebip(bnew,trim(filename))
          call writebiq(bnew,trim(filename))

          !
          ! 
          deallocate(bnew%x,bnew%y,bnew%t,bnew%sst,bnew%err)
          deallocate(bd%x,bd%y,bd%t,bd%sst,bd%err)


        end if  ! multiplier>0.

      end do

      end program

