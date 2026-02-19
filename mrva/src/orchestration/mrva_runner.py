#! /usr/bin/env python

import os
import sys

# Add parent directories to path for mur_date import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
import mur_date  # noqa: E402

# makenrt.py
# near real-time front end for IDL based data extraction.

##### log file #####
logdir='/home/tmchin/logs'
logfile=logdir+'/mrvarun.log'

MURproductDir='/store/ghrsst/open/data/L4/GLOB/JPL/MUR'
MURbody='%04d%02d%02d-JPL-L4UHfnd-GLOB-v01-fv%s-MUR.nc.bz2'  # GDS 1.x
MURversion='03'

MRVAdir='.'

##### date range #####

year0=2011; day0=240  # start day.  THIS LINE NEEDS MORE AUTOMATION.
latency=7  # end day, in terms of the number of days prior to today.

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
  """returns day of year (doy) and year for TODAY (or simulated today)"""
  today = mur_date.today()  # Respects MUR_SIMULATED_DATE env var
  return( int(today.strftime("%j")), today.year )

(d,y)=todoy()
year1=y; day1=d-latency  # end day



#################### Start Execution #################### 

## check for executable compilation:


if not os.path.exists(MRVAdir+'/mrva'):
  sys.exit('ABORT: executable "mrva" not found.')
if not os.path.exists(MRVAdir+'/spgrid'):
  sys.exit('ABORT: executable "spgrid" not found.')
if not os.path.exists(MRVAdir+'/trimbip3'):
  sys.exit('ABORT: executable "trimbip3" not found.')
  


f = open(logfile,'w')

for year in span(year0,year1):

  d0=1; d1=daysInYear(year)
  if year==year0:
    d0=day0
  if year==year1:
    d1=day1

  for day in span(d0,d1):

      ## file directory & name:
      MURdir = MURproductDir+'/%04d/%03d/'%(year,day)
      (calendarday,month)=calday(day,year)
      MURfile=MURdir+MURbody%(year,month,calendarday,MURversion)

      ## 
      if os.path.exists(MURfile):
        f.write('exists: %s\n'%MURfile)
      else:

        mrvalogfile = logdir+'MRVA_%04d_%03d.log'%(year,day)
        g = open('MRVAcmd.m','w')
        g.write('whichdays={%d,%d:%d};\n'%(year,day,day))
        g.write('mrva3com;\n')
        g.close()
        #cmd='/usr/local/bin/matlab -nodisplay < MRVAcmd.m >& MRVA.log'
        #cmd='/usr/local/bin/matlab -nodisplay < MRVAcmd.m >& '+mrvalogfile
        cmd='/opt/matlab/R2012b/bin/matlab -nodisplay < MRVAcmd.m >& '+mrvalogfile
        #cmd='echo "'+cmd+'"'   # for testing only.
        os.system(cmd)

f.close()

