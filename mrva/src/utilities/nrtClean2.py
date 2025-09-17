#! /usr/bin/env python

# nrtClean.py
# version 0,  13.12.23

import os,sys
import datetime

testing=0  # set to 1 to test the script without executing download/MRVA.




##### target directories #####

ncdir='/nas/ftp/mur_sst/tmchin/GDS2/L4/GLOB/JPL/MUR/v4'
logdir='/home/tmchin/logs'


##### trash directories #####
ncdeldir='/nas/ftp/mur_sst/tmchin/delme/GDS2'


##### date range #####

scanLatency = 10 # [days] defines begin date.


#################### END Parameters #################### 


##### find dates:

def span(i1,i2,i3=1):
   """more intuitive than python's "range" """
   return range(i1,i2+i3/abs(i3),i3)

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
    if (yday-1)/months[m]==0:
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
(day2,year2)=todoy()
(day0,year0)=adjdoy(day2-scanLatency,year2) # start of rea run (if needed).



#################### Start Execution #################### 

#sys.exit('abort')



## make save list(s):

nclist=[]


for year in span(year0,year2):

  ncYearDir = ncdir+'/%04d'%(year)
  nclist.append(ncYearDir)


  d0=1; d2=daysInYear(year)
  if year==year0:
    d0=day0
  if year==year2:
    d2=day2


  for day in span(d0,d2):

    dayDir = ncYearDir+'/%03d'%(day)
    nrtDir = ncYearDir+'/%03dnrt'%(day)

    if os.path.exists(nrtDir) and not os.path.exists(dayDir):
      dayDir=nrtDir

    nclist.append(dayDir)


## move old files away:

for dirname, dirnames, filenames in os.walk(ncdir):
    #print dirname
    for subdirname in dirnames:
        #print subdirname
        name  = os.path.join(dirname, subdirname)
        name2 = os.path.join(ncdeldir, subdirname)
        if not name in nclist:
          if os.path.exists(name2):
            cmd="rm -r %s"%(name2)
            if testing==1:
              cmd='echo "'+cmd+'"'   # for testing only.
            os.system(cmd)
          cmd="mv -f %s %s/"%(name,ncdeldir)
          if testing==1:
            cmd='echo "'+cmd+'"'   # for testing only.
          os.system(cmd)


