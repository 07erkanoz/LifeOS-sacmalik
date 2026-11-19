import QtQuick
import QtQuick.Controls

TextField {
    id: f
    color: Theme.text
    placeholderTextColor: Theme.muted
    font.pixelSize: Theme.fs(13)
    selectByMouse: true
    implicitHeight: 34
    leftPadding: 10
    background: Rectangle {
        radius: 8; color: Theme.bg
        border.color: f.activeFocus ? Theme.user : Theme.line
    }
}
