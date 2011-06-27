#!/usr/bin/env python
# encoding=utf-8
# maintainer: rgaudin

import re
import urllib
import time
import logging
import thread

from django.conf import settings

from models import Message

logger = logging.getLogger(__name__)


def import_path(name):
    """ import a callable from full module.callable name """
    modname, _, attr = name.rpartition('.')
    if not modname:
        # single module name
        return __import__(attr)
    m = __import__(modname, fromlist=[attr])
    return getattr(m, attr)


def process_incoming_message(message):

    try:
        handler_func = import_path(settings.NOSMS_HANDLER)
    except AttributeError:
        message.status = Message.STATUS_ERROR
        message.save()
        logger.error(u"NO SMS_HANDLER defined while receiving SMS")
    except Exception as e:
        message.status = Message.STATUS_ERROR
        message.save()
        logger.error(u"Unbale to call SMS_HANDLER with %r" % e)
    else:
        try:
            thread.start_new_thread(handler_func, (message,))
        except Exception as e:
            message.status = Message.STATUS_ERROR
            message.save()
            logger.error(u"SMS handler failed on %s with %r" % (message, e))


def process_outgoing_message(message):
    """ fires a kannel-compatible HTTP request to send message """

    def _str(uni):
        try:
            return str(uni)
        except:
            return uni.encode('utf-8')

    # remove non digit from number
    identity = re.compile('\D').sub("", message.identity)

    # urlencode for HTTP get
    message_text = msg_enc = urllib.quote(_str(message.text))

    # send HTTP GET request to Kannel
    try:
        url = "http://%s:%d/cgi-bin/sendsms?" \
              "to=%s&from=&text=%s" \
              % (settings.NOSMS_TRANSPORT_HOST, \
                 settings.NOSMS_TRANSPORT_PORT, \
                 identity, message_text)
        # if there is a username/password, append to URL
        try:
            url = "%s&username=%s&password=%s" \
                  % (url, settings.NOSMS_TRANSPORT_USERNAME, \
                     settings.NOSMS_TRANSPORT_PASSWORD)
        except:
            pass
        res = urllib.urlopen(url)
        ans = res.read()
    except Exception, err:
        logger.error("Error sending message: %s" % err)

        # we'll try to send it again later
        message.status = Message.STATUS_CREATED
        message.save()
        return False

    # success
    if res.code == 202:
        if ans.startswith('0: Accepted'):
            kw = 'sent'
        elif ans.startswith('3: Queued'):
            kw = 'queued'
        else:
            kw = 'sent'

        logger.debug("message %s: %s" % (kw, message))
        message.status = Message.STATUS_PROCESSED
        message.save()

    # temporary error
    elif res.code == 503:
        logger.error("message failed to send (temporary error): %s" % ans)
        message.status = Message.STATUS_CREATED
        message.save()
    else:
        logger.error("message failed to send: %s" % ans)
        message.status = Message.STATUS_ERROR
        message.save()
