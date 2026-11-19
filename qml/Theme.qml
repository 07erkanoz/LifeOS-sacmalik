pragma Singleton
import QtQuick

// İki palet: koyu ve açık. Seçim ayarlarda saklanır (cfg.theme), Main.qml `dark`ı ona bağlar.
QtObject {
    property bool dark: true
    property real scale: 1.0                  // yazı boyutu: ayarlarda ve Ctrl +/−/0 ile, hatırlanır
    function fs(n) { return Math.round(n * scale) }

    // yüzeyler
    readonly property color bg:       dark ? "#0b0c11" : "#f4f5fa"
    readonly property color panel:    dark ? "#101219" : "#ffffff"
    readonly property color card:     dark ? "#161922" : "#ffffff"
    readonly property color cardHi:   dark ? "#1c202b" : "#eef0f6"
    readonly property color field:    dark ? "#151821" : "#ffffff"
    readonly property color line:     dark ? "#232735" : "#dfe2ec"
    readonly property color lineSoft: dark ? "#1b1f2a" : "#e8eaf1"
    // yazı
    readonly property color text:     dark ? "#eceef5" : "#1a1c25"
    readonly property color textDim:  dark ? "#aeb3c2" : "#4a4f60"
    readonly property color muted:    dark ? "#6b7083" : "#8b90a1"
    // vurgu
    readonly property color user:     "#8b5cf6"
    readonly property color userHi:   "#a78bfa"
    readonly property color danger:   dark ? "#f87171" : "#e04848"
    readonly property color ok:       dark ? "#34d399" : "#10b981"
    readonly property color link:     dark ? "#8fb3ff" : "#3b6fe0"
    readonly property real shadow:    dark ? 0.45 : 0.12
    readonly property real glow:      dark ? 0.07 : 0.10
    // ölçüler
    readonly property int radius: 14
    property int column: 880                 // mesaj sütunu: Main.qml pencere genişliğine bağlar (iki yana açılır)
    readonly property string mono: "JetBrains Mono, Fira Code, monospace"

    Behavior on dark { enabled: false }
}
