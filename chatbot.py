# -*- coding: utf-8 -*-
import logging
import os
import signal
import sys
from base64 import b64decode
from datetime import datetime
from logging.handlers import RotatingFileHandler, SMTPHandler
from threading import Event

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests.exceptions import ConnectionError

from db import Connection

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

MAX_COUNT = 6
MAX_DELAY = 10

DB_URL = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
URL = os.environ.get('URL')
LOGIN = os.environ.get('LOGIN')
PASSWORD = b64decode(os.environ.get('PASSWORD')).decode()
TG_TOKEN = os.environ.get('TG_TOKEN')
CHAT_ID = int(os.environ.get('CHAT_ID'))
ADMINS = os.environ.get('ADMINS')
MAIL_HOST = os.environ.get('MAIL_HOST')


def create_logger(name='Chatbot'):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    )
    logger.addHandler(stream_handler)

    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler('logs/{}.log'.format(name.lower()), maxBytes=102400, backupCount=10)
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')
    )
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    if ADMINS:
        mail_handler = SMTPHandler(
            mailhost=(MAIL_HOST, 25),
            fromaddr='no-reply@' + MAIL_HOST,
            toaddrs=ADMINS.split(';'),
            subject='{} Failure'.format(name)
        )
        mail_handler.setLevel(logging.ERROR)
        logger.addHandler(mail_handler)

    logger.info('{} startup'.format(name))
    return logger


def parse_page(data):
    """
    Выделяет необходимые параметры из страницы со списком событий.
    :param data: текст HTML-страницы
    :return: кортеж с количеством событий и количеством минут с появления первого
    """
    soup = BeautifulSoup(data, 'html.parser')
    events = soup.find_all('tr', {'bgcolor': '#FF0000'})
    if events:
        # последние расположены сверху, самое старое - внизу
        first = events[-1].find_all('td')
        event_time = first[1].text
        delta = datetime.now() - datetime.strptime(event_time, '%Y-%m-%d %H:%M:%S')
        delay = delta.seconds / 60
    else:
        delay = 0
    return len(events), delay


class Chatbot:
    def __init__(self):
        self.logger = create_logger()
        self.db_conn = Connection(DB_URL, self.logger)

        self.stop = Event()
        signal.signal(signal.SIGINT, self._exit_gracefully)
        signal.signal(signal.SIGTERM, self._exit_gracefully)

    def _exit_gracefully(self, signum, frame):
        self.stop.set()

    def send_telegram(self, text, chat_id=CHAT_ID):
        """
        Отправляет сообщение в телеграм.
        :param text: текст сообщения
        :param chat_id: id чата, в который будет отправлено сообщение
        :return: None
        """
        url = 'https://api.telegram.org/bot' + TG_TOKEN + '/sendMessage'
        response = requests.post(url, data={
            'chat_id': chat_id,
            'text': text
        })
        if response.status_code != 200:
            self.logger.error('Unable to post to Telegram: {} {}'.format(
                response.status_code, response.reason))

    def check_events(self):
        """
        Проверят страницу со списком событий и определяет необходимость
        привлечения сотрудников.
        :return: bool признак большого количества событий
        """
        try:
            response = requests.get(URL, auth=(LOGIN, PASSWORD))
        except ConnectionError:
            self.logger.error('Unable to access event page', exc_info=sys.exc_info())
        else:
            if response.status_code == 200:
                response.encoding = 'cp1251'
                count, delay = parse_page(response.text)
                if count >= MAX_COUNT or delay >= MAX_DELAY:
                    return True
            else:
                self.logger.warning('Bad response from event page: {} {}'.format(
                    response.status_code, response.reason))
        return False

    def run(self):
        """
        Запускает чат-бот, который раз в 15 секунд проверяет
        количество событий и сообщает в чат если необходимо отреагировать.
        :return: None
        """
        self.db_conn.set_parameter('cb_state', 'True')
        need = 0
        while True:
            many = self.check_events()
            need = 0 if not many else need + 1
            if need > 1:
                need = 0
                message = 'Требуется реакция:\n' + URL
                self.send_telegram(message)
                # засыпает на 5 минут чтобы не спамить
                self.stop.wait(285)
            if self.stop.is_set() or self.stop.wait(15):
                break
        self.db_conn.set_parameter('cb_state', 'False')
        self.logger.info('Chatbot terminated')


if __name__ == '__main__':
    cb = Chatbot()
    cb.run()
