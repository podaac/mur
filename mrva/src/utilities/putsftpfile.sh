#! /bin/sh
# "push" a file into GHRSST using sftp command.
# Usage:
#   putsftpfile sftp_account remote_directory input_path output_file

# example: 
#  % putsftpfile.sh   sftp-ghrsst@seafire   JPL-MUR-RTO/tmp   \
#   ./2010/087/20100328-JPL-L4UHfnd-NCAMERICA-v01-fv02-MUR.nc.gz   \
#   20100328-JPL-L4UHfnd-NCAMERICA-v01-fv02-MUR.nc.gz


if [ "$1" = "" ]
then
    echo ""
    echo "USAGE: % putsftpfile <user@machine> <remote-dir> <infilename>
<outfilename>"
    echo ""
    echo "example:  
 % putsftpfile.sh   sftp-ghrsst@seafire   JPL-MUR-RTO/tmp  \  
  ./2010/087/20100328-JPL-L4UHfnd-NCAMERICA-v01-fv02-MUR.nc.gz   \  
  20100328-JPL-L4UHfnd-NCAMERICA-v01-fv02-MUR.nc.gz"
    echo ""
    exit 1
fi

if [ "$2" = "" ]
then
    echo ""
    echo "USAGE: % putsftpfile <user@machine> <remote-dir> <infilename>
<outfilename>"
    echo ""
    echo "example:  % putsftpfile gftpin@seatide.jpl.nasa.gov JPL/tmp
droplet.txt droplet.txt.out"
    echo ""
    exit 1
fi
if [ "$3" = "" ]
then
    echo ""
    echo "USAGE: % putsftpfile <user@machine> <remote-dir> <infilename>
<outfilename>"
    echo ""
    echo "example:  % putsftpfile gftpin@seatide.jpl.nasa.gov JPL/tmp
droplet.txt droplet.txt.out"
    echo ""
    exit 1
fi

if [ "$4" = "" ]
then
    echo ""
    echo "USAGE: % putsftpfile <user@machine> <remote-dir> <infilename>
<outfilename>"
    echo ""
    echo "example:  % putsftpfile gftpin@seatide.jpl.nasa.gov JPL/tmp
droplet.txt droplet.txt.out"
    echo ""
    exit 1
fi

DESTINATION=$1
DIR=$2
IN_FILE=$3
OUT_FILE=$4

#echo "DIR = $DIR"
#echo "IN_FILE = $IN_FILE"
#echo "OUT_FILE = $OUT_FILE"

# Push the file to JPL/tmp, then rename it one directory up, 
# then change the owner and group setting to read and write.

sftp $DESTINATION <<FTP
   cd $DIR 
   put $IN_FILE $OUT_FILE
   ls
   rename $OUT_FILE ../$OUT_FILE
   quit
FTP

#   chmod 664 ../$OUT_FILE

