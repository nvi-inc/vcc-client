import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import shutil
import pexpect


from vcc import settings, vcc_cmd

logger = logging.getLogger('vcc')


# Manage interaction with drudg
class DRUDG:

    def __init__(self, ses_id, sta_id):
        self.ses_id, self.sta_id = ses_id.lower(), sta_id.lower()
        # Default timeout time (sec)
        self.timeout = 3
        self.modified = time.time()
        logger.info('drug initialized')

    # Look for specific pattern and provide selection
    def pattern_response(self, child, pattern, selection, end_on_error=True):
        try:
            if child.expect([pattern], timeout=self.timeout) == 0:
                logger.debug(f'pattern {pattern.encode()} {selection} - ok')
                if selection:
                    child.sendline(selection)
                return True
        except (pexpect.EOF, pexpect.TIMEOUT):
            pass
        logger.error(f'pattern {pattern.encode()} {selection} - not found')
        if end_on_error:
            child.close()
        return False

    # start interactive drudg
    def drudg(self, filename):

        logger.info(f'processing {filename}')

        schedule = Path(settings.Folders.schedule, os.path.basename(filename))
        logger.debug(f'DRUDG {schedule}')
        self.modified = os.stat(schedule).st_mtime

        cmd = f'{settings.DRUDG.exec} {schedule}'
        logger.debug(f'DRUDG {cmd}')

        # Run drudg with the working directory set to Folders.schedules
        try:
            child = pexpect.spawn(cmd, cwd=settings.Folders.schedule)
        except (pexpect.ExceptionPexpect, BaseException) as exc:
            return f'Problem starting drudg: {str(exc)}'

        # Select station
        if not self.pattern_response(child, "which station .*all\) \? ", self.sta_id.capitalize()):
            return "Did not get prompt for a station name"
        # Expected pattern is a ? prompt and select SNP (3) option
        if not self.pattern_response(child, "\r\n \?", '3'):
            return "Did not get a menu prompt"
        # Make SNAP File
        if not self.expect_drudg_prompts(child, "12", settings.Folders.snap):
            return "Could not create SNAP file"
        # Make PRC File. Depending on how skedf.ctl is set up, the user may be prompted for extra data
        if not self.expect_drudg_prompts(child, "9", settings.Folders.proc):
            return 'Could not create PROC file'
        # Change output dest
        lst = os.path.join(settings.Folders.list, f'{self.ses_id}{self.sta_id}.lst')
        self.pattern_response(child, "else enter in filename or PRINT.\r\n", lst, end_on_error=False)
        for i in range(3):
            [child.expect(expected) for expected in ["no change", "\r\n"]]
            child.sendline("")
        self.pattern_response(child, " \?", "5", end_on_error=False)
        self.pattern_response(child, " \?", "0", end_on_error=False)
        self.pattern_response(child, "DRUDG DONE", None, end_on_error=False)
        child.close()

        return None

    def expect_drudg_prompts(self, child, next_selection, folder):
        # Array of possible prompts and corresponding reply
        misc = settings.DRUDG.Misc
        prompts = ["\r\n \?", "purge existing", "Enter TPI period in centiseconds", "Enter in cont_cal action",
                   "Enter in cont_cal_polarity", "Enter in vsi_align", "Use setup_proc", "vdif_single_thread_per_file"]
        replies = ['', 'y', misc.tpi_period, misc.cont_cal_action, misc.cont_cal_polarity, misc.vsi_align,
                   misc.setup_proc, misc.vdif_single_thread_per_file]
        done = False
        while not done:
            try:
                index = child.expect(prompts, timeout=self.timeout)  # Get prompt index
            except (pexpect.EOF, pexpect.TIMEOUT):
                return False
            # and deal with the output...
            if index == 0:
                logger.debug('prompts: done')
                done = True  # back to main drudg prompt
            else:
                logger.debug(f"prompts: {prompts[index]}: {str(replies[index])}")
                child.sendline(str(replies[index]))

            # look for information from drudg on where the snp or prc files were placed (if they were created):
            match = re.search("From file:\s\S*\sTo\s\S*\s\S*\s(\S*)", child.before.decode('utf-8'))
            if not match:
                match = re.search("PROCEDURE LIBRARY FILE\s(\S*)", child.before.decode('utf-8'))
            if match:
                logger.debug(f'prompts: match {match.group(1)}')
                outfile = match.group(1).strip()
                logger.debug(f'outfile 1 {outfile}')
                outfile = outfile if os.path.dirname(outfile) else os.path.join(settings.Folders.schedule, outfile)
                logger.debug(f'outfile 2 {outfile}')
                # Set modified time to same than schedule file
                os.utime(outfile, (time.time(), self.modified))
                # Move to appropriate folder
                if folder != os.path.dirname(outfile):
                    shutil.move(outfile, os.path.join(folder, os.path.basename(outfile)))

        # Provide next selection
        child.sendline(next_selection)
        return True


def drudg_it(ses_id, vex=False):
    def file_time(f):
        return f'{datetime.fromtimestamp(f.lstat().st_mtime).strftime("%Y-%m-%d %H:%M")}'

    if not (sta_id := settings.get_user_code('NS')):
        vcc_cmd('message-box',
                "-t 'NO privilege for this action' -m 'Only Network Station can run drudg on FS' -i 'warning'")
        return

    sta_id = sta_id.lower()

    drudg = DRUDG(ses_id, sta_id)
    filename = f'{ses_id}.{"vex" if vex else "skd"}'
    if err := drudg.drudg(filename):
        print(f'drudg failed!: {err}')
    else:
        print('drudg successful!')
        filepath = Path(settings.Folders.schedule, filename)
        print(f'{str(filepath):30s} {file_time(filepath)}')
        for file in [Path(settings.Folders.snap, f'{ses_id}{sta_id}.snp'),
                     Path(settings.Folders.proc, f'{ses_id}{sta_id}.prc'),
                     Path(settings.Folders.list, f'{ses_id}{sta_id}.lst')]:
            print(f'{str(file):30s} {file_time(file) if file.exists() else "not found"}')

