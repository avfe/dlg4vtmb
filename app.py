import sys
from PyQt5.QtWidgets import QApplication
from mainwindow import MainWindow

def main():
    app = QApplication(sys.argv)
    mw = MainWindow()
    # проверка и предложение восстановить автосохранённую сессию
    mw.check_recovery_on_start()
    mw.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
