      program mrva

! multi-resolution variational analysis
! mike chin, 13.10.17


      use spmm
      use filemod


      ! parameters:
      integer maxbip
      real SSToffset   
      parameter(maxbip=50)         ! max number of bip data files.
      parameter(SSToffset=273.15)  ! Kelvin at freezing.


      real wx,wy,wxx,wyy,wxy
      data wx,wy,wxx,wyy,wxy/0.05,0.05,0.01,0.01,0.02/  ! ncamrica1

      real, allocatable:: w1(:,:),w2(:,:),w11(:,:),w22(:,:),w12(:,:)
      real, allocatable:: lon(:),lat(:)


      ! spm data:
      real, allocatable:: csp(:),dsp(:),rhoscale(:),wgt(:)
      type(bip) :: bg, d(maxbip)


      ! data sets:
      character*128 filename
      
      ! name list:
      real lonmin,lonmax,latmin,latmax
      integer L0,LF
      real decay(1:12)  
      character*128 bgfile ! background bip field.
      character*128 coefile ! background coefficient field.
      character*128 bipfile(3,maxbip) ! main data files.
      integer nbipfile  ! number of data files.

      namelist /input/ lonmin,lonmax,latmin,latmax, L0,LF,decay,
     &                 bgfile,coefile,nbipfile,bipfile


!
! input parameters from namelist file:
!
      open(7,file='mrva.nml',form='formatted',status='old')
      read(7,nml=input)
      close(7)

      print*,'background: ',trim(bgfile)
      print*,'initial coefficient: ',trim(coefile)




!
! read background:
!
      print*,'Background:'
      call readbip(bg,trim(bgfile))
      if(bg%n>0) then
          print*,'  ... box: ',minval(bg%x),maxval(bg%x),
     &                         minval(bg%y),maxval(bg%y)
          print*,'  ... time range: ',minval(bg%t),maxval(bg%t)
          print*,'  ... sst: ',sum(bg%sst)/bg%n,
     &                         minval(bg%sst),maxval(bg%sst)
          print*,'  ... err: ',sum(bg%err)/bg%n,
     &                         minval(bg%err),maxval(bg%err)
      end if


!      
! read data files:
!

      print*,'Data:'
      do m=1,nbipfile
        read(bipfile(1,m),*) d(m)%La
        read(bipfile(2,m),*) d(m)%Lb
        filename=trim(bipfile(3,m))
        call readbip(d(m),trim(filename))
        if(d(m)%n>0) then
          print*,'  from',d(m)%La,' to',d(m)%Lb,', ',d(m)%n,' points.'
          print*,'  ... box: ',minval(d(m)%x),maxval(d(m)%x),
     &                         minval(d(m)%y),maxval(d(m)%y)
          print*,'  ... time range: ',minval(d(m)%t),maxval(d(m)%t)
          print*,'  ... sst: ',sum(d(m)%sst)/d(m)%n,
     &                         minval(d(m)%sst),maxval(d(m)%sst)
          print*,'  ... err: ',sum(d(m)%err)/d(m)%n,
     &                         minval(d(m)%err),maxval(d(m)%err)
        end if
      end do




!      
! spm domain:
!
      mz=1
      nv=1
      gridgrain=45./(2**L0)  ! degrees.
      hx = lonmax-lonmin
      hy = latmax-latmin
!      mx0 = nint( hx/gridgrain +0.5 )
!      my0 = nint( hy/gridgrain +0.5 )
!      hx = abs(gridgrain*mx0 - hx)/2
!      hy = abs(gridgrain*my0 - hy)/2
      mx0 = int( hx/gridgrain ) +1
      my0 = int( hy/gridgrain ) +1
      hx = (gridgrain*mx0 - hx)/2
      hy = (gridgrain*my0 - hy)/2
      xmin=lonmin
      xmax=lonmax
      if(cix==0) xmin=lonmin-hx
      if(cix==0) xmax=lonmax+hx
      ymin=latmin-hy
      ymax=latmax+hy



!
! scale loop:
!
      do L=L0,LF

!      print*,'Starting: L=',L

        if(L.eq.L0) then
            mx=mx0*(2**(L-L0)); my=my0*(2**(L-L0))
            call spmInit
            call initialcoeff(ios,dsp,trim(coefile))
            if(ios==0) then  ! non-zero initial coefficient field:
              ! do residuals:
              do m=1,nbipfile
               do n=1,d(m)%n
                 call spmPoint(1,1,dsp,d(m)%x(n),d(m)%y(n),0,0,hx,hy,tL)
                 d(m)%sst(n)=d(m)%sst(n)-tL
               end do
              end do
              print*,'INITIALIZED WITH: ',trim(coefile)
            else  ! no external inital coefficient:
              allocate(dsp(coeffSize)); dsp=0.0  ! initialized to zero.
              print*,'NO INITIAL COEFFICIENTS.'
            end if
        else ! scale up:
            mx=mx*2; my=my*2
            call spmRefresh
            allocate(dsp(coeffSize)); dsp=0.0
            call spmDoubleGrid(csp,nx,ny,dsp)
            deallocate(csp)
        end if


        ! Euler-Lagrange equation:

!      print*,'Thin Plate ',L
          allocate(w1(mx3,my3),w2(mx3,my3),lon(mx3),lat(my3))
          allocate(w11(mx3,my3),w22(mx3,my3),w12(mx3,my3))
          call spmXY(lon,lat)
          deg2rad=atan(1.)*4./180.
          do j=1,my3
          do i=1,mx3
            w1(i,j)=1./max( (cos(lat(j)*deg2rad))**2, 0.03)
            w11(i,j)=1./max( (cos(lat(j)*deg2rad))**4, 0.03)
          end do
          end do
          c=20.
          if(L.le.2) c=20.
          if(L.ge.9) c=40.
          w11(:,:)=c*wxx*w11(:,:)
          w1(:,:)=c*wx*w1(:,:)
          w12(:,:)=c*wxy; w2(:,:)=c*wy; w22(:,:)=c*wyy
!      print*,'parameter allocated.'
          
          call spmThinPlateIJ(w1,w2,w11,w22,w12,1,1)
          print*,L,'thinplate done.'
          deallocate(w1,w2,lon,lat,w11,w22,w12)
          totalweight=0.0

        ! background field:
          if(L.eq.L0) then
            if(bg%n>0) then
              call spmData(1,1,bg%x,bg%y,bg%sst,bg%err,bg%n)
              totalweight=totalweight+sum(bg%err(:))
              deallocate(bg%x,bg%y,bg%t,bg%sst,bg%err)
            else
              print*,'NO BACKGROUND.'
            end if
          end if
 
        ! data incoporation:
          rho=0.8*exp(-(45./2**L)/4.0)
          do m=1,nbipfile
            if(L.ge.d(m)%La .and. L.le.d(m)%Lb) then
              allocate(rhoscale(mx3*my3))
              call spmRhoWeightScale(rhoscale,rho,
     &                               d(m)%x,d(m)%y,d(m)%n)
              allocate(wgt(d(m)%n))
              Ldecay=L
              if(Ldecay.lt.1) Ldecay=1
              wgt(:)=d(m)%err(:)*exp(-(d(m)%t(:)/decay(Ldecay))**2)
              if(L.ge.2) then
                if(L.ge.11) then
                  call spmDataScaleP(1,1,d(m)%x,d(m)%y,
     &                              d(m)%sst,wgt,d(m)%n,rhoscale)
                else
                  call spmDataScaleQ(1,1,d(m)%x,d(m)%y,
     &                              d(m)%sst,wgt,d(m)%n,rhoscale)
                end if
              else
                call spmDataScale(1,1,d(m)%x,d(m)%y,
     &                              d(m)%sst,wgt,d(m)%n,rhoscale)
              end if
              deallocate(rhoscale)
              print*,'included ',trim(bipfile(3,m)),' @',L
              totalweight=totalweight+sum(wgt(:))
              deallocate(wgt)
            end if
          end do

        ! compute the coefficients:
          allocate(csp(coeffSize)); csp=0.0

          print*,'(L,rho,totalweight)=',L,rho,totalweight
          if(totalweight.gt.0.0001) then
            epsln=1.0e-8
!            if(L.ge.11) epsln=1.0e-6
            if(L.ge.9) epsln=1.0e-3
            call spmPCG(csp,mx3*my3,epsln,1.0e3)
          end if

        ! data residual:
          do m=1,nbipfile
            if(L.ge.d(m)%La .and. L.le.d(m)%Lb) then
              jblk=d(m)%n/nProcessors  ! nProcessors set in spmm.f
!$OMP PARALLEL DO PRIVATE(n,tL) SCHEDULE(STATIC,jblk)
              do n=1,d(m)%n
                call spmPoint(1,1,csp,d(m)%x(n),d(m)%y(n),0,0,hx,hy,tL)
                d(m)%sst(n)=d(m)%sst(n)-tL
              end do
!$OMP END PARALLEL DO
            end if
            print*,trim(bipfile(3,m)),':'
            if(d(m)%n.le.0) then
              print*,'  ... no content.'
            else
              r=sum(d(m)%err(:))
              if (r.le.0.) then
                ave=0.; std=-1.
              else
                ave=sum(d(m)%sst(:)*d(m)%err(:))/r
                std=sqrt(sum(((d(m)%sst(:)-ave)**2)*d(m)%err(:))/r)
              end if
              print*,'  off =',ave
              print*,'  RMS =',std
              print*,'  Max =',maxval(d(m)%sst,1,d(m)%err>1.0)
     &      ,'@(',d(m)%x(maxloc(d(m)%sst,1,d(m)%err>1.0)),
     &            d(m)%y(maxloc(d(m)%sst,1,d(m)%err>1.0)),')'
              print*,'  Min =',minval(d(m)%sst,1,d(m)%err>1.0)
     &      ,'@(',d(m)%x(minloc(d(m)%sst,1,d(m)%err>1.0)),
     &            d(m)%y(minloc(d(m)%sst,1,d(m)%err>1.0)),')'


!              !! outlier removal:
!              if(L.ge.d(m)%La .and. L.le.d(m)%Lb) then
!                std=std*4  ! outlier definition.
!!$OMP PARALLEL DO PRIVATE(n) SCHEDULE(STATIC,jblk)
!                do n=1,d(m)%n
!                if(abs(d(m)%sst(n)).gt.std) d(m)%err(n)=0.0
!                end do
!!$OMP END PARALLEL DO
!              end if
            end if  ! d(m)%n.

!            if(L.eq.LF) then  ! write "anomaly" data file:
!              write(filename,'("mrva_",i3.3,".a",i2.2)') m,L
!              call writebiq(d(m),trim(filename))
!            end if

          end do



        ! accumulate:
          csp(:)=dsp(:)+csp(:)
          deallocate(dsp)

        ! write coefficient field:
          write(filename,'("mrva.c",i2.2)') L
          call writecoeff(csp,filename)

        ! write uncertainty coefficient field:
          write(filename,'("mrva.u",i2.2)') L
          call writevarcoeff(filename)

       ! write map file:
       call writeGlobeMap(csp,L)


        ! remember old grid:
          nx=mx
          ny=my
      end do  ! L.

      end program

!!!!!!!!!!
      subroutine writeGlobeMap(csp,L)
      use spmm
      real csp(*)
      integer L
      integer nlon,nlat
      parameter(nlon=360*4,nlat=180*4)
      real lon(nlon),lat(nlat),sst(nlon,nlat)
      sstref=273.15
      dx=0.25; dy=0.25
      do n=1,nlon
        lon(n)=n*dx-180.
      end do
      do n=1,nlat
        lat(n)=n*dy-90.
      end do
      do j=1,nlat
        y=lat(j)
        do i=1,nlon
          x=lon(i)
          call spmPoint(1,1,csp,x,y,0,0,dx,dy,sst(i,j))
          sst(i,j)=sst(i,j)+sstref
        end do
      end do
      write(80+L) nlon,nlat
      write(80+L) sst,lon,lat
      end subroutine


