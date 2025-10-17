#!/bin/bash

echo "    --> Installing RCLONE"
if [ -f "/usr/bin/rclone" ] ; then
	echo "      Already installed ^^"
	echo "      rm -rf /usr/bin/rclone #to removeit and restart this install"
	exit
fi
if [ ! -f /usr/bin/curl ] || [ ! -f /usr/bin/unzip ] ; then
	apt-get update
	apt-get install -y curl unzip
fi
case "$(uname -i)" in
  x86_64)
    ARCHDL=amd64
    ;;
  aarch64)
    ARCHDL=arm64
    ;;
  *)
    echo "Unknown architecture: $(uname -i)"
    ;;
esac

echo "ARCHDL=$ARCHDL"

curl -o /tmp/rclone.zip https://downloads.rclone.org/rclone-current-linux-${ARCHDL}.zip
cd /tmp
unzip rclone.zip
cd rclone-*-linux-${ARCHDL}

# Copy binary file
cp rclone /usr/local/bin/
chown root:root /usr/local/bin/rclone
chmod 755 /usr/local/bin/rclone


