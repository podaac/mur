#! /usr/bin/python3.12

# nrtMRVA.py
# near real-time (nrt) front end for Matlab based data extraction and MRVA.
# Both "nrt" and "reanalysis" (rea) runs of MRVA are considered.

# version 3a, 13.01.24
# version 4,  13.02.12
#             14.04.30 (bug fix)
#             16.05.31 (ice download code switch)

import os,sys
import datetime

testing=0  # set to 1 to test the script without executing download/MRVA.


##### work directories #####

#mrvaDir='/seaward/tmchin/nrtMRVA'
mrvaDir='/nas6/nrtMRVA'
makebicDir='/tmp/makebic'



##### log file #####

logdir='/home/tmchin/logs'
logfile=logdir+'/nrtMRVA.log'

if testing==1:
  logdir='/tmp/logs'
  logfile=logdir+'/nrtMRVA.log'
  os.system('mkdir -p '+logdir)

##### date range #####

nrtLatency = 1  # [days] latency of nrt; defines the end date of nrt run.
#nrtLatency = 4  # [days] latency of nrt; defines the end date of nrt run.
reaLatency = 4  # [days] latency of reanalysis (rea); defines rea end date.
scanLatency = 9 # [days] defines begin date.
  ## These numbers must be in increasing order.



##### ice file parameters #####

# Output directory of ice and land files are set in
#   /home/tmchin/ice/mat/makeicefiles.m
# There is no dayrange for these files.

# Maybe desirable to have "stablat" feature (see below) as well.


##### buoy file parameters #####

#buoyoutputDirRoot = '/nas2/fnmoc/'
buoyoutputDirRoot = '/nas2/iquam/'
buoydayrange = 3
buoystablat = 2  # [days] latency when the data source is stable.

  
##### L2P file sensor list #####

## "stablat" is latency [days] that specifies the date when the source data 
## are stable, until then nrtMRVA.py would download repeatedly overwriting
## the previous downloads.

sensors=( # sensor, binRootDir, region, La, Lb, dayrange, stablat:
  ('AMSR2R','/nas2/bic/AMSR2R','Global',2,8,  2, 2),
  ('MODISA','/nas2/bic/MODISA','Global',2,12, 2, 2),
  ('MODIST','/nas2/bic/MODIST','Global',2,12, 2, 3),
  ('AVMTAG','/nas2/bic/AVMTAG','Global',2,9,  2, 2),
  ('AVMTBG','/nas2/bic/AVMTBG','Global',2,9,  2, 2),
)
#  ('AVH19G','/nas2/bic/AVH19G','Global',2,9,  2, 2),
#  ('AVH18G','/nas2/bic/AVH18G','Global',2,9,  2, 2),
#  ('VIIRSN','/nas2/bic/VIIRSN','Global',2,12, 2, 2),
#  ('AMSREA','/nas2/bic/AMSREA','Global',2,8,  2, 2),
#  ('WINSAT','/nas2/bic/WINSAT','Global',2,8,  2, 3),


##### MRVA production check #####

#MURproductDir='/store/ghrsst/open/data/L4/GLOB/JPL/MUR'
MURproductDir='/nas/ftp/mur_sst/tmchin/L4/GLOB/JPL/MUR'
MURbody='%04d%02d%02d-JPL-L4UHfnd-GLOB-v01-fv%s-MUR.nc.bz2'  # GDS 1.x
#MURbody='%04d%02d%02d090000-JPL-L4_GHRSST-SSTfnd-MUR-GLOB-v02.0-fv%s.nc4'#GDS2.0
MURversion='04'

  # These MUST BE CONSISTENT WITH SETTINGS in mrva4com.m and csp2nc4.m




#################### END Parameters #################### 


##### find dates:

def span(i1,i2,i3=1):
   """more intuitive than python's "range" """
   return range(i1,int(i2+i3/abs(i3)),i3)

def daysInYear(year):
  if ( year%4==0 and ((year%100)!=0 or (year%400)==0) ):
    return(366)
  else:
    return(365)

def calday(yday,year):
  months=[0,31,28,31,30,31,30,31,31,30,31,30,31]
  if ( year%4==0 and ((year%100)!=0 or (year%400)==0) ):
    months[2]=29
  for m in span(1,12):
    months[m]=months[m]+months[m-1]
  for m in span(1,12):
    if yday <= months[m]:
      month=m
      day=yday-months[m-1]
      return (day,month)
  sys.exit('ABORT calday: yearday value out of range')

def todoy():
  """returns day of year (doy) and year for TODAY"""
  import datetime
  today=datetime.date.today()
  return( int(today.strftime("%j")), today.year )

def adjdoy(doy,year):
  """adjusts (doy,year) values to a neighboring year if necessary"""
  if doy<1:
    year=year-1
    doy=doy+daysInYear(year)
  if doy>daysInYear(year):
    doy=doy-daysInYear(year)
    year=year+1
  return (doy,year)

def ordday(doy,year):
  """returns the cummulative days since 1 A.D. January 0th"""
  return datetime.date(year,1,1).toordinal()-1+doy



## begin/end dates of analysis runs:
(d,y)=todoy()

(day2,year2)=adjdoy(d-nrtLatency,y)  # end of nrt run.
(day1,year1)=adjdoy(d-reaLatency,y)  # end of rea run/pre-start of nrt run.
(day0,year0)=adjdoy(d-scanLatency,y) # start of rea run (if needed).



#################### Start Execution #################### 

##
## prepare the executables:
##

## save home dir:
homeDir=os.getcwd()

## clean the destination:
os.system('rm -fr '+mrvaDir)
os.system('rm -fr '+makebicDir)

## copy the code-sets: 
os.system('cp -a /home/tmchin/cyc4 '+mrvaDir)
os.system('mkdir -p '+makebicDir)

## compile MRVA:
os.chdir(mrvaDir)
os.system('make')


##
## MAIN LOOP:
##

#sys.exit('abort')


f = open(logfile,'a')
(day,year)=todoy()
f.write("---------- Today = Year %d Day %d ----------\n"%(year,day))
f.write("           from (%d,%d) to (%d,%d) \n"%(year0,day0,year2,day2))


for year in span(year0,year2):

  d0=1; d2=daysInYear(year)
  if year==year0:
    d0=day0
  if year==year2:
    d2=day2

  for day in span(d0,d2):


    ##
    ## near real time (nrt) or reanalysis (rea) ?
    ##
    if ordday(day,year) > ordday(day1,year1):
      realtime = 1
      f.write("  ======== Intrim run for Year %d Day %d ========\n"%(year,day))
    else:
      realtime = 0
      f.write("  ======== Final run for Year %d Day %d ========\n"%(year,day))


    ##
    ## ice & landmask files:
    ##
    os.chdir(makebicDir)

    icefile="makeice%04d%03d.m"%(year,day)
    fice = open(icefile,'w')
    fice.write("path('/home/tmchin/ice/mat',path);")
    fice.write("year=%d; day=%d;"%(year,day))

    fice.write("[icesstfile,landicefile]=makeicefiles(year,day,'p01');")
    fice.write("if length(landicefile),")
    fice.write("eval(sprintf('! gzip -f %s &',landicefile)); end;")
    fice.write("if length(icesstfile),")
    fice.write("eval(sprintf('! gzip -f %s &',icesstfile)); end;")

    fice.write("[icesstfile,landicefile]=makeicefiles(year,day,'p011');")
    fice.write("if length(landicefile),")
    fice.write("eval(sprintf('! gzip -f %s &',landicefile)); end;")
    fice.write("if length(icesstfile),")
    fice.write("eval(sprintf('! gzip -f %s &',icesstfile)); end;")

    fice.close()
    #cmd="/usr/local/bin/matlab -nodisplay < %s"%(icefile)
    #cmd="/opt/matlab/R2012b/bin/matlab -nodisplay < %s"%(icefile)
    cmd="/opt/matlab/R2021b/bin/matlab -nodisplay < %s"%(icefile)

    if testing==1:
      cmd='echo "'+cmd+'"'   # for testing only.

    f.write('%s\n'%cmd)
    os.system(cmd)


    ##
    ## buoy files:
    ##
    os.chdir(makebicDir)

    for dt in span(-buoydayrange,buoydayrange):

      ## data day is (d,y):
      (d,y) = adjdoy( day+dt, year ) 

      if datetime.date.today().toordinal() - ordday(d,y) < 0: # future date?
        continue  # ... skip to the next data day.

      ## determine stability of source file(s):
      if datetime.date.today().toordinal() - ordday(d,y) < buoystablat:
        rewrite=1
      else:
        rewrite=0

      if realtime==1:
        rewrite=0

      ## file directory & name:
      buoyoutputDir = buoyoutputDirRoot+'%04d'%(y)

      if not os.path.exists(buoyoutputDir):
        f.write('making directory '+buoyoutputDir+'\n')
        os.mkdir(buoyoutputDir)

      #buoyfile='%s/GLOBAL_FNMOCs_%04d_%03d.bin'%(buoyoutputDir,y,d)
      buoyfile='%s/Global_IQUAM0_%04d_%03d.bii'%(buoyoutputDir,y,d)

      ## 
      if os.path.exists(buoyfile) and (rewrite==0):
        f.write('keeping old %s\n'%buoyfile)
      else:

        #cmd='/usr/local/bin/idl -rt=./FNMOCwrapper.sav -args'
        #cmd=cmd+" %d %d '%s'" % (y,d,buoyoutputDir)

        ## IQUAM:
        iqmatfile="makeiquam%04d_%03d.m"%(y,d)
        fiq = open(iqmatfile,'w')
        fiq.write("path('/home/tmchin/iquam',path);")
        fiq.write("year=%d; day=%d; rewrite=%d;"%(y,d,rewrite))
        fiq.write("makedailyiquam(year,day,rewrite);")
        fiq.close()
        #cmd="/usr/local/bin/matlab -nodisplay < %s"%(iqmatfile)
        #cmd="/opt/matlab/R2012b/bin/matlab -nodisplay < %s"%(iqmatfile)
        cmd="/opt/matlab/R2021b/bin/matlab -nodisplay < %s"%(iqmatfile)
        
        if testing==1:
          cmd='echo "'+cmd+'"'   # for testing only.

        f.write('%s\n'%cmd)
        os.system(cmd)

    ## end buoy files.


    ##
    ## L2P files:
    ##
    os.chdir(makebicDir)

    for isensor in range(len(sensors)):

      sensor=sensors[isensor][0]
      bicRootDir=sensors[isensor][1]
      region=sensors[isensor][2]
      dayrange=sensors[isensor][5]
      stablat=sensors[isensor][6]


      for dt in span(-dayrange,dayrange):

        ## data day is (d,y):
        (d,y) = adjdoy( day+dt, year ) 

        if datetime.date.today().toordinal() - ordday(d,y) < 0: # future date?
          continue  # ... skip to the next data day.

        ## determine stability of source file(s):
        if datetime.date.today().toordinal() - ordday(d,y) < stablat:
          rewrite=1
        else:
          rewrite=0


        ## file directory & name:
        bicdir='%s/%04d'%(bicRootDir,y)
        bicfile='%s/%s_%s_%04d_%03d.bic.gz'%(bicdir,region,sensor,y,d)

        ## 
        if os.path.exists(bicfile) and (rewrite==0):
          f.write('keeping old %s\n'%bicfile)
        else:

          if not os.path.exists(bicdir):
            f.write('making directory '+bicdir+'\n')
            os.makedirs(bicdir)
          #cmd='/usr/local/bin/idl -rt=./dailywrapper.sav -args'
          #cmd=cmd+" %d %d" % (y,d)
          #cmd=cmd+" '%s' '%s' '%s'" % (region,sensor,bicdir)
          l2pcmdfile="makebiccmd_%s_%04d_%03d.m"%(sensor,y,d)
          if os.path.exists(l2pcmdfile):
            f.write('just written %s\n'%bicfile)
            rewrite=0
          fbic = open(l2pcmdfile,'w')
          fbic.write("path('/home/tmchin/makebin/mat',path);\n")
          fbic.write("year=%d; day=%d; sensor='%s';\n"%(y,d,sensor))
          fbic.write("bicdir='%s'; region='%s';\n"%(bicRootDir,region))
          fbic.write("rewrite=%d;\n"%(rewrite))
          fbic.write("l2p2bic(sensor,region,bicdir,year,day,rewrite);\n")
          fbic.close()
          #cmd = "/usr/local/bin/matlab -nodisplay < %s"%(l2pcmdfile)
          #cmd = "/opt/matlab/R2012b/bin/matlab -nodisplay < %s"%(l2pcmdfile)
          cmd="/opt/matlab/R2021b/bin/matlab -nodisplay < %s"%(l2pcmdfile)
 
          if testing==1:
            cmd='echo "'+cmd+'"'   # for testing only.

          f.write('%s\n'%cmd)
          os.system(cmd)

    ## end L2P files.


    ##
    ## MRVA:
    ##
    os.chdir(mrvaDir)

    MURdir = MURproductDir+'/%04d/%03d/'%(year,day)
      ## MURdir is made if absent in ./csp2nc.m
    (calendarday,month)=calday(day,year)
    MURfile=MURdir+MURbody%(year,month,calendarday,MURversion)

    ## 
    if os.path.exists(MURfile) and (realtime==0):
      f.write('KEEPING OLD %s\n'%MURfile)
    else:

      mrvalogfile = logdir+'/MRVA_%04d_%03d.log'%(year,day)
      g = open('MRVAcmd.m','w')
      g.write('whichdays={%d,%d:%d};\n'%(year,day,day))
      g.write('realtime=%d;\n'%(realtime))
      g.write('mrva4com;\n')
      g.close()
      #cmd='/usr/local/bin/matlab -nodisplay < MRVAcmd.m >& MRVA.log'
      #cmd='/usr/local/bin/matlab -nodisplay < MRVAcmd.m >& '+mrvalogfile
      #cmd='/opt/matlab/R2012b/bin/matlab -nodisplay < MRVAcmd.m >& '+mrvalogfile
      cmd="/opt/matlab/R2021b/bin/matlab -nodisplay < MRVAcmd.m >& "+mrvalogfile
 
      if testing==1:
        cmd='echo "'+cmd+'"'   # for testing only.
        f.write('MRVA: realtime=%d;\n'%(realtime))
      
      f.write('%s\n'%cmd)
      os.system(cmd)

    ## end MRVA.


os.chdir(homeDir)
f.close()

## clean up:
##os.system('rm -fr '+mrvaDir)

