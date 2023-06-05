#!/bin/bash
VOLSLIST="/config/bns/backup_vols.txt"
PRESCRIPT="/config/bns/backup_pre_script.sh"

if [[ -f ${VOLSLIST} ]]
then
	DATADIRS=$(cat ${VOLSLIST} |egrep -v "^#") 
else
	echo "Volumes to Backup file is missing : ${VOLSLIST}"
	exit
fi

if [ -z "${HOSTID}" ]; then
	export HOSTID=$(hostname)
	echo "Host ID is not set, setting it to ${HOSTID}"
else
	echo "Host ID is set : ${HOSTID}"
fi

if [ -z "${BKP_BASE_DIR}" ]; then
	echo "Backup Base dir is not set in var BKP_BASE_DIR"
	exit
else
	export BKPDIR="${BKP_BASE_DIR}/${HOSTID}"
fi

if [ -z "${MAXBKP}" ]; then
	export MAXBKP=7
fi
echo "Max backups to keep : ${MAXBKP}"

echo "Base dir for volumes : ${SRC_VOL_BASE}"

if [[ -f /config/rclone/rclone.conf ]]
then
	echo "Found Rclone config in /config/rclone/rclone.conf"
else
	echo "Rclone config missing in /config/rclone/rclone.conf"
	exit
fi


# Main
export RUNTMSTP=$(date +%Y%m%d)
if [ -z "${SYNCONLY}" ]; then

	if [[ -f ${PRESCRIPT} ]]
	then
		echo "Found Prescript ... running it"
		${PRESCRIPT}
	fi

	mkdir -p ${BKPDIR} 2>&1 >/dev/null

	for datadir in ${DATADIRS} 
	do
		echo "----------------------------------"
		
		if [ -d ${SRC_VOL_BASE}/${datadir} ]; then
			echo "Directory '${SRC_VOL_BASE}/${datadir}' exists"
			mkdir -p ${BKPDIR}/${datadir} 2>&1 >/dev/null
			echo "Creating backup ${BKPDIR}/${datadir}/${datadir}_${RUNTMSTP}.tar.gz"
			tar czpf ${BKPDIR}/${datadir}/${datadir}_${RUNTMSTP}.tar.gz ${SRC_VOL_BASE}/${datadir}

			echo "Cleaning old backups to keep only ${MAXBKP} files"
			bkp_files=($(ls ${BKPDIR}/${datadir} |sort -r))
			n=$MAXBKP
			for file in "${bkp_files[@]}"; do
				if [ "$n" -le 0 ]; then
					rm "${BKPDIR}/${datadir}/$file"
					echo "-Removing '${BKPDIR}/${datadir}/$file'"
				else
					echo "+Keeping '${BKPDIR}/${datadir}/$file'"
					((n--))
				fi
			done
		else
			echo "Volume/dir '${SRC_VOL_BASE}/${datadir}' does not exists ... Skipping"
		fi
	done
fi
echo "----------------------------------"
echo "----------------------------------"
echo "Syncing to ${RCLONE_TARGET} ${RCLONE_PREFIX}/${HOSTID}/${RCLONE_SUFFIX}"
rclone -v --progress sync ${BKPDIR} ${RCLONE_TARGET}:${RCLONE_PREFIX}/${HOSTID}/${RCLONE_SUFFIX}
