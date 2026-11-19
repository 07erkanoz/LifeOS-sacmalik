import QtQuick
import QtQuick.Controls

Button {
    id: b
    property color accent: Theme.user
    implicitHeight: 34
    hoverEnabled: true
    opacity: enabled ? 1 : 0.4
    contentItem: Text {
        text: b.text; color: b.hovered ? Theme.text : Theme.textDim
        font.pixelSize: Theme.fs(12); font.weight: Font.Medium
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 9
        color: b.down ? Qt.rgba(b.accent.r, b.accent.g, b.accent.b, 0.25)
             : b.hovered ? Qt.rgba(b.accent.r, b.accent.g, b.accent.b, 0.12) : "transparent"
        border.color: b.hovered ? b.accent : Theme.line
        Behavior on color { ColorAnimation { duration: 120 } }
    }
}
