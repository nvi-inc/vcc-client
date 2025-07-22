#!/bin/bash


# Create virtual environment

while ! [ -d "$vcc_dir" ]
do
    printf "Enter full directory of the vcc folder if not default (default= /usr2/vcc):"
    read vcc_dir
    vcc_dir=${vcc_dir:-/usr2/vcc}
    if ! [ -d "$vcc_dir" ]; then
    printf "\nCould not find $vcc_dir.\n"
    fi
done

# fetch latest vcc from github

cd $vcc_dir
python3 -m venv vcc_venv
source vcc_venv/bin/activate
python -m pip install --upgrade pip
python -m pip install git+https://github.com/nvi-inc/vcc-client.git


# get required paths


while ! [ -f "$path_config" ]
do
    printf "\nEnter full path for config.txt if not default (default=vcc_dir/config.txt): \n"
    read path_config
    path_config=${path_config:-$vcc_dir/config.txt}
    if ! [ -f "$path_config" ]; then
    printf "\nCould not find $path_config.\n" 
    fi
done


while ! [ -f "$path_key" ]
do
    echo  "Enter full path for oper's private ssh key if not default (default= /usr2/oper/.ssh/id_rsa): "
    read path_key
    path_key=${path_key:-/usr2/oper/.ssh/id_rsa}
    if ! [ -f "$path_key" ]; then
    printf "\nCould not find $path_key.\n"
    fi
done


# activate virtual enviroment and install

source "${vcc_dir}/vcc_venv/bin/activate"
vcc-config $path_config $path_key

# test the basic installation

vcc test
deactivate

printf "\n Adding vccmon to systemctl\n"

cd $vcc_dir
cp -i vccmon.service /etc/systemd/system/
chmod 644 /etc/systemd/system/vccmon.service
systemctl start vccmon
systemctl enable vccmon
systemctl status vccmon # check that it works and active

printf "\n Checking if VCC executable folder is in the PATH of oper"
path_oper=$(su - oper -c 'echo $PATH')

if [[ ":$path_oper:" == *":$vcc_dir/bin:"* ]]; then
  printf "\nVCC executables alread in PATH of oper! OK."
else
  printf "\nPATH=\$PATH:$vcc_dir/bin">> /usr2/oper/.profile
  printf "\nAdded VCC to the PATH of oper"
fi
	  


printf "\nVCC installation complete!\n"


