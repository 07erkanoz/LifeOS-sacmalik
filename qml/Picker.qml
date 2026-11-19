import QtQuick
import QtQuick.Controls

// Seçim kutusu: tıkla → listeden seç, ya da elle yaz.
Item {
    id: c
    property string value
    property var items: []      // ["id", ...] ya da [{value, label}, ...]
    readonly property var norm: items.map(function(m) {
        return typeof m === "string" ? { value: m, label: "" } : { value: m.value, label: m.label || "" } })
    function labelOf(v) { for (var i = 0; i < norm.length; i++) if (norm[i].value === v) return norm[i].label; return "" }
    property string emptyLabel: "CLI varsayılanı"
    signal picked(string v)
    property bool typed: false     // yalnızca kullanıcı yazınca süz

    implicitHeight: 34
    implicitWidth: 200

    function choose(v) { field.text = v; c.picked(v); pop.close() }

    TextField {
        id: field
        anchors.fill: parent
        text: c.value
        placeholderText: c.emptyLabel
        placeholderTextColor: Theme.muted
        color: Theme.text; font.pixelSize: Theme.fs(13); font.family: "monospace"
        leftPadding: 10; rightPadding: 34
        selectByMouse: true
        verticalAlignment: Text.AlignVCenter
        onTextEdited: { c.typed = true; c.picked(text.trim()); if (!pop.visible && c.items.length) pop.open() }
        onActiveFocusChanged: if (activeFocus && c.items.length) pop.open()
        background: Rectangle {
            radius: 8; color: Theme.bg
            border.color: field.activeFocus || pop.visible ? Theme.user : Theme.line
        }
    }

    // ok butonu: her zaman listeyi açar/kapar
    MouseArea {
        width: 34; height: parent.height
        anchors.right: parent.right
        cursorShape: Qt.PointingHandCursor
        onClicked: pop.visible ? pop.close() : pop.open()
        Text {
            anchors.centerIn: parent
            text: pop.visible ? "▴" : "▾"; color: Theme.textDim; font.pixelSize: Theme.fs(14)
        }
    }

    Popup {
        id: pop
        y: c.height + 4
        onAboutToShow: c.typed = false
        width: c.width
        height: Math.min(list.contentHeight + 8, 320)
        padding: 4
        margins: 8
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        background: Rectangle { radius: 10; color: Theme.card; border.color: Theme.line }

        ListView {
            id: list
            anchors.fill: parent
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            // yazılan metne göre süz
            model: {
                var q = c.typed ? field.text.trim().toLowerCase() : ""
                var hit = function(m) { return !q || m.value === c.value || m.value.toLowerCase().indexOf(q) >= 0
                                               || m.label.toLowerCase().indexOf(q) >= 0 }
                var all = c.norm.filter(hit)
                if (!all.length) all = c.norm
                return [{ value: "", label: "— CLI varsayılanı —" }].concat(all)
            }
            delegate: Rectangle {
                required property var modelData
                required property int index
                readonly property bool sel: index > 0 && modelData.value === c.value
                width: list.width
                height: 34; radius: 6
                color: ma.containsMouse ? Theme.line : (sel ? Qt.rgba(1, 1, 1, 0.05) : "transparent")
                Text {
                    id: lab
                    anchors.verticalCenter: parent.verticalCenter
                    x: 10
                    width: Math.min(implicitWidth, parent.width - 20 - (idTxt.visible ? idTxt.implicitWidth + 12 : 0))
                    text: index === 0 ? modelData.label : (modelData.label || modelData.value)
                    color: index === 0 ? Theme.muted : (sel ? Theme.text : Theme.textDim)
                    font.pixelSize: Theme.fs(13)
                    font.bold: sel
                    elide: Text.ElideRight
                }
                Text {
                    id: idTxt
                    visible: index > 0 && modelData.label.length > 0
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: parent.right; anchors.rightMargin: 10
                    text: modelData.value
                    color: Theme.muted; font.pixelSize: Theme.fs(11); font.family: "monospace"
                }
                MouseArea {
                    id: ma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: c.choose(modelData.value)
                }
            }
        }
    }
}
