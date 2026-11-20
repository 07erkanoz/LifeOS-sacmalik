import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Oda kuralları: yalnız bu sohbetin. Ayarlardaki oda anlaşması bütün odalarındır; bunlar onun üstüne eklenir.
// Kaydedince odaya görünür yazılır; ajanlara oda bilgisiyle gider (yeni oturumda, yeni katılan ajana ve kurallar
// her değiştiğinde süren oturuma bir kez) ve uzun sohbette döküm kırpılsa da düşmez.
Popup {
    id: d
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(620, win.width - 80)
    height: Math.min(col.implicitHeight + 44, win.height - 80)
    padding: 22
    onAboutToShow: {
        var r = room.rules
        txt.text = r.text || ""
        defBox.checked = r.isDefault
        txt.forceActiveFocus()
    }
    enter: Transition { ParallelAnimation {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 200; easing.type: Easing.OutCubic } } }
    background: Rectangle { radius: 16; color: Theme.panel; border.color: Theme.line }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    contentItem: ColumnLayout {
        id: col
        spacing: 12
        Text { text: "Oda kuralları"; color: Theme.text; font.pixelSize: Theme.fs(18); font.weight: Font.Bold }
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: Theme.fs(12)
            text: "Yalnız bu sohbet için. Ajanlar bunları oda bilgisiyle alır: odaya katılınca, oturumları yeniden "
                + "açılınca ve sen kuralları her değiştirdiğinde. Uzun sohbette de unutulmaz. "
                + "Ayarlardaki oda anlaşması bütün odalarda geçerli kalır."
        }
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 220
            radius: 10; color: Theme.bg
            border.color: txt.activeFocus ? Theme.user : Theme.line
            ScrollView {
                anchors.fill: parent; anchors.margins: 2
                TextArea {
                    id: txt
                    wrapMode: TextArea.Wrap
                    color: Theme.text
                    placeholderText: "Örnek: Plan yapmadan üretim yok. Karar verilmeden kod yazılmaz.\n"
                                   + "Plana itiraz etmek plan dışı değildir.\n"
                                   + "Yeni bilgi ya da itiraz yoksa yazmayın."
                    placeholderTextColor: Theme.muted
                    font.pixelSize: Theme.fs(13)
                    selectByMouse: true
                    background: null
                }
            }
        }
        CheckBox {
            id: defBox
            text: "Yeni sohbetler de bu kurallarla açılsın"
            indicator: Rectangle {
                x: defBox.leftPadding; anchors.verticalCenter: parent.verticalCenter
                width: 18; height: 18; radius: 5
                color: defBox.checked ? Theme.user : Theme.bg
                border.color: defBox.checked ? Theme.user : Theme.line
                Text { anchors.centerIn: parent; visible: defBox.checked; text: "✓"; color: "white"
                       font.pixelSize: Theme.fs(11); font.bold: true }
            }
            contentItem: Text { leftPadding: defBox.indicator.width + 8; text: defBox.text; color: Theme.textDim
                                font.pixelSize: Theme.fs(12); verticalAlignment: Text.AlignVCenter }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            GhostButton {
                visible: !!room.rules.defaultText && txt.text !== room.rules.defaultText
                text: "Varsayılan kuralları getir"
                onClicked: { txt.text = room.rules.defaultText; defBox.checked = true }
            }
            Item { Layout.fillWidth: true }
            GhostButton { text: "Vazgeç"; onClicked: d.close() }
            Button {
                id: save
                text: "Kaydet"
                implicitHeight: 34
                contentItem: Text { text: save.text; color: "white"; font.pixelSize: Theme.fs(13); font.bold: true
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                                    leftPadding: 10; rightPadding: 10 }
                background: Rectangle { radius: 9; color: save.down ? Theme.userHi : Theme.user }
                onClicked: { room.setRules(txt.text, defBox.checked); d.close() }
            }
        }
    }
}
