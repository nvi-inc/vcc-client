
VLBI Communications Center (VCC) client
---------------------------------------

The VLBI Communications Center (VCC) client software is used to upload/retreive information on VCC server.


The VCC access is based on roles. There are 6 possible roles. Each user has a special key for each role.<br>
1 - Network Station (NS).    Any station listed in catalog.<br>
2 - Coordinator Center (CC). Only GSFC has that role.<br>
3 - Operations Center (OC).  Any group listed in the SKED CODES from the master-format.txt file<br>
4 - Analysis Center (AC).    Any group listed in the SUBM CODES from the master-format.txt file<br>
5 - Correlator (CO).         Any group listed in the CORR CODES from the master-format.txt file<br>
6 - Dashboard (DB).          Any user.<br>

The special keys are store in a vcc.ctl configuration file.<br>
To get that file, you need to send your public ssh key to ivscc@nviinc.com along with the specific roles and group of your organisation.<br>
Many keys can be stored in the control file.

You may create a pair of key using

ssh-keygen -t rsa -b 4096

For Network Station (NS) users or Field System (FS) users, you need to provide the public key of 'oper' account. 

Special instructions will be sent with the encoded vcc.ctl file.
