import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from paperbreakfast.config import EmailConfig
from paperbreakfast.digest.builder import DigestPayload
from paperbreakfast.models.db import DigestRun

logger = logging.getLogger(__name__)


class Mailer:

    def __init__(self, config: EmailConfig, smtp_password: str):
        self._config = config
        self._password = smtp_password

    def send(self, payload: DigestPayload) -> bool:
        cfg = self._config

        if not cfg.smtp_user or not cfg.from_addr or not cfg.to_addrs:
            logger.error(
                "Email not configured. Set smtp_user, from_addr, and to_addrs in config.yaml."
            )
            return False

        date_str = datetime.utcnow().strftime("%b %d")
        subject = f"PaperBreakfast — {payload.paper_count} papers — {date_str}"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg.from_addr
        msg["To"] = ", ".join(cfg.to_addrs)
        msg.attach(MIMEText(payload.html, "html", "utf-8"))

        smtp = None
        try:
            if cfg.smtp_port == 465:
                smtp = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port)
            else:
                smtp = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port)
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()

            smtp.login(cfg.smtp_user, self._password)
            smtp.sendmail(cfg.from_addr, cfg.to_addrs, msg.as_string())

            logger.info(f"Digest sent to {cfg.to_addrs} ({payload.paper_count} papers)")
            DigestRun.create(paper_count=payload.paper_count, success=True)
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            self._record_failure(payload.paper_count, str(e))
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            self._record_failure(payload.paper_count, str(e))
        except Exception as e:
            logger.error(f"Failed to send digest: {e}")
            self._record_failure(payload.paper_count, str(e))
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass  # already failed — don't mask the original error

        return False

    def _record_failure(self, paper_count: int, error: str):
        try:
            DigestRun.create(paper_count=paper_count, success=False, error_message=error)
        except Exception:
            pass  # don't let a DB write failure mask the original error
