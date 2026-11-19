import QtQuick
import QtQuick.Layouts

Rectangle {
    id: p
    property string name
    property string sub
    property string usageLine            // CLI'ın bildirdiği 5 saatlik ve haftalık kota
    property bool usageFull               // kotası dolu
    property bool active
    property bool online
    property bool clickable: true
    property alias hovered: ma.containsMouse
    property color tint
    signal clicked

    implicitHeight: usageLine ? 66 : 54
    radius: 12
    color: active ? Qt.rgba(p.tint.r, p.tint.g, p.tint.b, 0.14)
         : ma.containsMouse && clickable ? Theme.card : "transparent"
    border.color: active ? Qt.rgba(p.tint.r, p.tint.g, p.tint.b, 0.5) : "transparent"
    Behavior on color { ColorAnimation { duration: 180 } }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 10; anchors.rightMargin: 10
        spacing: 12
        Item {
            width: 34; height: 34
            Rectangle {   // konuşma halkası
                anchors.centerIn: parent
                width: 34; height: 34; radius: 17
                visible: p.active
                color: "transparent"; border.color: p.tint; border.width: 2
                opacity: 0; scale: 1
                SequentialAnimation on scale {
                    running: p.active; loops: Animation.Infinite
                    NumberAnimation { from: 1; to: 1.5; duration: 900; easing.type: Easing.OutQuad }
                }
                SequentialAnimation on opacity {
                    running: p.active; loops: Animation.Infinite
                    NumberAnimation { from: 0.8; to: 0; duration: 900 }
                }
            }
            Rectangle {
                anchors.fill: parent; radius: 17
                color: p.tint
                opacity: p.online ? 1 : 0.35
                Text { anchors.centerIn: parent; text: p.name.charAt(0); color: "white"; font.bold: true; font.pixelSize: Theme.fs(15) }
            }
            Rectangle {
                width: 10; height: 10; radius: 5
                anchors.right: parent.right; anchors.bottom: parent.bottom
                color: p.online ? "#3ddc84" : "#555a6b"; border.color: Theme.panel; border.width: 2
            }
        }
        ColumnLayout {
            spacing: 1
            Layout.fillWidth: true
            Text { text: p.name; color: Theme.text; font.pixelSize: Theme.fs(13); font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
            Text { text: p.sub; color: p.active ? p.tint : Theme.muted; font.pixelSize: Theme.fs(11); elide: Text.ElideRight; Layout.fillWidth: true }
            Text {
                visible: p.usageLine !== ""
                text: (p.usageFull ? "⛔ kota doldu · " : "") + p.usageLine
                color: p.usageFull ? Theme.danger : Theme.muted
                font.pixelSize: Theme.fs(10); font.family: Theme.mono
                elide: Text.ElideRight; Layout.fillWidth: true
            }
        }
    }
    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        enabled: p.clickable
        cursorShape: p.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: p.clicked()
    }
}
