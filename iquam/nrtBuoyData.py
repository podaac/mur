#! /usr/bin/python3.12

# nrtBuoyData.py

import os,sys
import datetime

testing=0  # set to 1 to test the script without executing download/MRVA.

makebicDir='/tmp/makebic'
os.system('rm -fr '+makebicDir)
os.system('mkdir -p '+makebicDir)
homeDir=os.getcwd()

##### log file #####

logdir = '/home/tmchin/logs'
logfile = logdir+'/buoy.log'


##### buoy file parameters #####

buoyoutputDirRoot = '/nas2/iquam/'
buoydayrange = 3
buoystablat = 2  # [days] latency when the data source is stable.


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
    if yday < months[m]:
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
        #cmd="/usr/local/bin/matlab -nodesktop < %s"%(iqmatfile)
        #cmd="/opt/matlab/R2012b/bin/matlab -nodisplay < %s"%(iqmatfile)
        cmd="/opt/matlab/R2021b/bin/matlab -nodisplay < %s"%(iqmatfile)

        if testing==1:
          cmd='echo "'+cmd+'"'   # for testing only.

        f.write('%s\n'%cmd)
        os.system(cmd)

    ## end buoy files.

os.chdir(homeDir)
f.close()

