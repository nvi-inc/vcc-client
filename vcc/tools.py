import sys

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget

from vcc import message_box


class MainWnd(QMainWindow):
    def __init__(self, title, text, information=None):
        super().__init__()
        self.setCentralWidget(QWidget(self))

        self.hide()
        message_box(title, text, information)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Display message')
    parser.add_argument('title')
    parser.add_argument('message')
    parser.add_argument('information', nargs='?')

    args = parser.parse_args()

    app = QApplication(sys.argv)
    wnd = MainWnd(args.title, args.message, args.information)


if __name__ == '__main__':

    sys.exit(main())
