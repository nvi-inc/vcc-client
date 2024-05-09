import smtplib
import logging
from subprocess import Popen, PIPE
from email.mime.text import MIMEText

from vcc import settings

logger = logging.getLogger('vcc')


def send_mail(subject, message):
    try:
        to = settings.Mail.recipients
        process = Popen(["mail", "-s", subject, to], stdin=PIPE, stdout=PIPE)
        process.stdin.write(message)
        process.communicate()
        process.stdin.close()
        return None
    except Exception as exc:
        return str(exc)


def smtp_mail(subject, message):

    try:
        msg = MIMEText(message, 'plain')
        msg['Subject'] = subject
        msg['From'] = settings.Mail.sender

        conn = smtplib.SMTP(settings.Mail.server, settings.Mail.port)
        if settings.Mail.password:
            conn.login(settings.Mail.sender, settings.Mail.password)
        conn.sendmail(settings.Mail.sender, settings.Mail.recipients, msg.as_string())
        return ''
    except Exception as exc:
        return str(exc)
    finally:
        conn.quit()


def mail_it(subject, message):
    if settings.Mail.notification == 'mail':  # Use mail system
        err = send_mail(subject, message)
    elif settings.Mail.notification == 'smtp':  # Use smtp server
        err = smtp_mail(subject, message)
    else:  # Do not send email
        logger.info(f'no email sent [{subject}]')
        return None

    logger.error(f'email failed [{subject}]') if err else logger.info(f'email sent [{subject}]')
    return None



