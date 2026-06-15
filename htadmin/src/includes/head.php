<?php
# head.php — Talixman OT Security — User Management
include_once ('tools/util.php');
if (!isset($ini)) {
    $ini = read_config();
}
error_reporting(E_ALL);
?>
<!DOCTYPE html>
<html lang="fr" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?php echo htmlspecialchars($ini['app_title'] ?? 'Talixman — User Management'); ?></title>
<link rel="icon"          type="image/x-icon" href="X.ico">
<link rel="shortcut icon"                     href="X.ico">

<!-- Bootstrap CSS conservé pour la logique PHP -->
<link rel="stylesheet" href="bootstrap.css" crossorigin="anonymous">
<link rel="stylesheet" href="styles/style.css">

<!-- jQuery conservé (nécessaire pour les formulaires htadmin) -->
<script src="script/jquery-1.12.0.min.js"></script>
<script src="script/script.js"></script>
<!-- bootstrap.min.js RETIRÉ — remplacé par JS natif -->

<style>
/* ══════════════════════════════════════════════════════
   VARIABLES
   ══════════════════════════════════════════════════════ */
:root {
    --tx-b:      #6b1d3a;   /* bordeaux */
    --tx-b2:     #8a2449;
    --tx-b3:     #4a1228;
    --tx-o:      #e05a1e;   /* orange */
    --tx-navy:   #111820;
    --tx-bg:     #f2f1ef;
    --tx-sur:    #ffffff;
    --tx-sur2:   #f9f8f7;
    --tx-txt:    #1a1a1a;
    --tx-txt2:   #555;
    --tx-muted:  #999;
    --tx-bord:   #e0ddd9;
    --tx-bord2:  #ccc9c4;
    --tx-nh:     58px;      /* navbar height */
    --tx-r:      10px;      /* radius */
    --tx-shadow: rgba(107,29,58,.1);
}
[data-theme="dark"] {
    --tx-bg:    #0d1520;
    --tx-sur:   #172030;
    --tx-sur2:  #1e2e48;
    --tx-txt:   #edf1f7;
    --tx-txt2:  #9ab0cc;
    --tx-muted: #5a7898;
    --tx-bord:  #283d58;
    --tx-bord2: #324f70;
}

/* ══════════════════════════════════════════════════════
   BASE
   ══════════════════════════════════════════════════════ */
*,*::before,*::after { box-sizing: border-box; }

body {
    background:  var(--tx-bg)   !important;
    color:       var(--tx-txt)  !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI',
                 Roboto, Helvetica, Arial, sans-serif !important;
    padding-top: var(--tx-nh)   !important;
    min-height:  100vh;
    transition:  background .3s, color .3s;
}

/* ══════════════════════════════════════════════════════
   NAVBAR
   ══════════════════════════════════════════════════════ */
.tx-nav {
    position:        fixed;
    top:0; left:0; right:0;
    height:          var(--tx-nh);
    background:      var(--tx-navy);
    border-bottom:   2px solid var(--tx-b);
    display:         flex;
    align-items:     center;
    padding:         0 28px;
    z-index:         9999;
    box-shadow:      0 2px 20px rgba(0,0,0,.45);
    gap:             0;
}

/* Logo image seul — PAS de texte lien */
.tx-nav-logo {
    height:          30px;
    width:           auto;
    display:         block;
    mix-blend-mode:  lighten;
    filter:          brightness(1.1);
    flex-shrink:     0;
}

/* Séparateur vertical */
.tx-sep {
    width:      1px;
    height:     26px;
    background: rgba(255,255,255,.14);
    margin:     0 22px;
    flex-shrink: 0;
}

/* Badge "User Management" centré dans la navbar */
.tx-nav-badge {
    font-size:      1rem;
    font-weight:    600;
    color:          #d83036;
    letter-spacing: .12em;
    text-transform: uppercase;
    flex:           1;           /* pousse le toggle à droite */
}

/* Toggle dark/light */
.tx-theme {
    display:     flex;
    align-items: center;
    gap:         8px;
    flex-shrink: 0;
}
.tx-icon {
    font-size:   1.2rem;
    opacity:     1;
    cursor:      pointer;
    user-select: none;
    line-height: 1;
    transition:  opacity .2s;
}
.tx-icon:hover { opacity: 1; }
.tx-sw {
    position: relative;
    width:    40px; height: 22px;
    cursor:   pointer; display: block;
}
.tx-sw input { position:absolute; opacity:0; width:0; height:0; }
.tx-track {
    position:      absolute; inset:0;
    background:    #3a3a3a;
    border-radius: 22px;
    transition:    background .3s;
}
.tx-sw input:checked + .tx-track { background: var(--tx-b); }
.tx-thumb {
    position:      absolute;
    top:3px; left:3px;
    width:16px; height:16px;
    background:    #fff;
    border-radius: 50%;
    transition:    transform .3s;
    box-shadow:    0 1px 4px rgba(0,0,0,.35);
    pointer-events: none;
}
.tx-sw input:checked ~ .tx-thumb { transform: translateX(18px); }

/* Masquer nav Bootstrap */
.navbar,.navbar-default,.navbar-header,
.navbar-collapse,.navbar-nav,.navbar-toggle { display:none !important; }

/* ══════════════════════════════════════════════════════
   CONTAINER
   ══════════════════════════════════════════════════════ */
.container {
    max-width:  860px !important;
    padding:    32px 20px 56px !important;
    animation:  txFade .45s ease both;
}
@keyframes txFade {
    from { opacity:0; transform:translateY(-8px); }
    to   { opacity:1; transform:translateY(0); }
}

/* ══════════════════════════════════════════════════════
   PANELS → CARTES
   ══════════════════════════════════════════════════════ */
.panel {
    background:    var(--tx-sur)   !important;
    border:        1px solid var(--tx-bord) !important;
    border-radius: var(--tx-r)     !important;
    box-shadow:    0 4px 28px var(--tx-shadow) !important;
    overflow:      hidden;
    margin-bottom: 24px !important;
    transition:    box-shadow .2s;
}
.panel:hover { box-shadow: 0 8px 36px rgba(107,29,58,.14) !important; }

.panel-default>.panel-heading {
    background:    linear-gradient(135deg,var(--tx-b),var(--tx-b3)) !important;
    color:         #fff !important;
    border:        none !important;
    padding:       15px 22px !important;
    border-radius: 0 !important;
    display:       flex;
    align-items:   center;
    gap:           10px;
}
.panel-default>.panel-heading::before {
    content:''; display:inline-block;
    width:3px; height:17px;
    background:var(--tx-o);
    border-radius:2px; flex-shrink:0;
}
.panel-default>.panel-heading .panel-title,
.panel-default>.panel-heading h3,
.panel-default>.panel-heading h4 {
    color:#fff !important;
    font-size:.92rem !important;
    font-weight:700 !important;
    letter-spacing:.06em;
    text-transform:uppercase;
    margin:0 !important;
}
.panel-body {
    background: var(--tx-sur) !important;
    padding:    28px 26px !important;
}
.panel-footer {
    background:   var(--tx-sur2) !important;
    border-top:   1px solid var(--tx-bord) !important;
    padding:      14px 22px !important;
    display:      flex;
    align-items:  center;
    justify-content: space-between;
    flex-wrap:    wrap;
    gap:          10px;
}

/* ══════════════════════════════════════════════════════
   TITRES DE FORMULAIRES
   ══════════════════════════════════════════════════════ */
h2, h3, h4 {
    color:          var(--tx-txt) !important;
    font-weight:    700 !important;
}
/* Titre principal de page */
h2:first-child {
    font-size:      1.45rem !important;
    border-bottom:  2px solid var(--tx-o) !important;
    padding-bottom: 10px !important;
    margin-bottom:  24px !important;
}
/* Sous-titre de section (ex: "Create or update user:") */
h3 {
    font-size:      1rem !important;
    color:          var(--tx-b) !important;
    letter-spacing: .02em;
    margin-bottom:  16px !important;
    display:        flex;
    align-items:    center;
    gap:            8px;
}
h3::before {
    content:'';
    display:inline-block;
    width:3px; height:16px;
    background:var(--tx-o);
    border-radius:2px;
}

/* ══════════════════════════════════════════════════════
   FORMULAIRES
   ══════════════════════════════════════════════════════ */
.form-control {
    background:    var(--tx-sur)   !important;
    color:         var(--tx-txt)   !important;
    border:        1px solid var(--tx-bord2) !important;
    border-radius: 8px !important;
    box-shadow:    none !important;
    padding:       11px 15px !important;
    height:        auto !important;
    font-size:     .91rem;
    transition:    border-color .2s, box-shadow .2s;
}
.form-control:focus {
    border-color:  var(--tx-b) !important;
    box-shadow:    0 0 0 3px rgba(107,29,58,.12) !important;
    outline:       none !important;
}
.form-control::placeholder { color:var(--tx-muted) !important; }

.form-group         { margin-bottom:16px !important; }
.form-group label,
.control-label {
    font-weight:   600 !important;
    color:         var(--tx-txt) !important;
    font-size:     .84rem !important;
    margin-bottom: 6px !important;
    display:       block;
    letter-spacing:.01em;
}

/* Input avec icône */
.input-group { width:100%; }
.input-group-addon {
    background:    var(--tx-sur2)  !important;
    border:        1px solid var(--tx-bord2) !important;
    border-right:  none !important;
    color:         var(--tx-b)     !important;
    border-radius: 8px 0 0 8px    !important;
    padding:       0 13px !important;
    font-size:     .95rem;
}
.input-group .form-control { border-radius: 0 8px 8px 0 !important; }

/* ══════════════════════════════════════════════════════
   BOUTONS
   ══════════════════════════════════════════════════════ */
.btn {
    font-weight:   600 !important;
    border-radius: 8px !important;
    padding:       10px 24px !important;
    font-size:     .88rem !important;
    letter-spacing:.01em;
    transition:    all .2s !important;
    cursor:        pointer;
    border:        none !important;
}
.btn-primary,
input[type="submit"],
button[type="submit"] {
    background:  linear-gradient(135deg,var(--tx-b),var(--tx-b3)) !important;
    color:       #fff !important;
    box-shadow:  0 2px 10px rgba(107,29,58,.28) !important;
}
.btn-primary:hover:not(:disabled),
input[type="submit"]:hover,
button[type="submit"]:hover {
    background:  linear-gradient(135deg,var(--tx-b2),var(--tx-b)) !important;
    transform:   translateY(-1px) !important;
    box-shadow:  0 5px 18px rgba(107,29,58,.38) !important;
}
.btn-primary:active { transform:translateY(0) !important; }
.btn-default {
    background:  var(--tx-sur)   !important;
    border:      1px solid var(--tx-bord2) !important;
    color:       var(--tx-txt2)  !important;
}
.btn-default:hover {
    border-color: var(--tx-b) !important;
    color:        var(--tx-b) !important;
}
.btn-danger {
    background:  linear-gradient(135deg,#c0392b,#922b21) !important;
    color:       #fff !important;
    box-shadow:  0 2px 8px rgba(192,57,43,.22) !important;
}
.btn-danger:hover {
    transform:   translateY(-1px) !important;
    box-shadow:  0 5px 14px rgba(192,57,43,.35) !important;
}
.btn-sm {
    padding:       7px 16px !important;
    font-size:     .82rem !important;
    border-radius: 6px !important;
}

/* ══════════════════════════════════════════════════════
   BOUTON DÉCONNEXION — flottant en bas à droite
   ══════════════════════════════════════════════════════ */
.tx-logout {
    position:      fixed;
    bottom:        28px;
    right:         28px;
    display:       flex;
    align-items:   center;
    gap:           8px;
    background:    linear-gradient(135deg,var(--tx-b),var(--tx-b3));
    color:         #fff;
    border:        none;
    border-radius: 50px;
    padding:       11px 22px;
    font-size:     .86rem;
    font-weight:   700;
    letter-spacing:.04em;
    text-transform:uppercase;
    cursor:        pointer;
    box-shadow:    0 4px 20px rgba(107,29,58,.35);
    text-decoration:none;
    transition:    all .25s;
    z-index:       888;
}
.tx-logout:hover {
    background:    linear-gradient(135deg,var(--tx-b2),var(--tx-b));
    transform:     translateY(-2px);
    box-shadow:    0 8px 28px rgba(107,29,58,.45);
    color:         #fff;
    text-decoration:none;
}
.tx-logout svg { width:16px; height:16px; flex-shrink:0; }

/* ══════════════════════════════════════════════════════
   TABLES
   ══════════════════════════════════════════════════════ */
.table-responsive {
    border-radius: var(--tx-r);
    overflow:      hidden;
    border:        1px solid var(--tx-bord) !important;
    box-shadow:    0 2px 14px var(--tx-shadow);
}
.table { margin-bottom:0 !important; }
.table>thead>tr>th {
    background:      var(--tx-navy) !important;
    color:           #fff !important;
    border:          none !important;
    padding:         13px 16px !important;
    font-size:       .77rem !important;
    font-weight:     700 !important;
    letter-spacing:  .1em;
    text-transform:  uppercase;
}
.table>tbody>tr>td {
    padding:         12px 16px !important;
    border-color:    var(--tx-bord) !important;
    vertical-align:  middle !important;
    color:           var(--tx-txt) !important;
    background:      var(--tx-sur) !important;
    font-size:       .9rem;
    transition:      background .15s;
}
.table-striped>tbody>tr:nth-of-type(odd)>td {
    background: var(--tx-sur2) !important;
}
.table>tbody>tr:hover>td { background:#f5ecf0 !important; cursor:pointer; }
[data-theme="dark"] .table>tbody>tr:hover>td { background:#2a1825 !important; }

/* ══════════════════════════════════════════════════════
   ALERTES
   ══════════════════════════════════════════════════════ */
.alert {
    border:        none !important;
    border-radius: 8px !important;
    padding:       12px 18px !important;
    font-weight:   500 !important;
    font-size:     .9rem;
    display:       flex;
    align-items:   center;
    gap:           10px;
}
.alert-success { background:#e6f5ed !important; color:#1d6e3d !important; }
.alert-danger  { background:#fde8e8 !important; color:#9b1c1c !important; }
.alert-warning { background:#fff8e6 !important; color:#7b5800 !important; }
.alert-info    { background:#e6f0fd !important; color:#1a5cb5 !important; }
[data-theme="dark"] .alert-success { background:#0d2e1a !important; }
[data-theme="dark"] .alert-danger  { background:#2e0d0d !important; }
[data-theme="dark"] .alert-warning { background:#2e2000 !important; }
[data-theme="dark"] .alert-info    { background:#0d1e3a !important; }

/* ══════════════════════════════════════════════════════
   SCROLLBAR
   ══════════════════════════════════════════════════════ */
::-webkit-scrollbar       { width:6px; height:6px; }
::-webkit-scrollbar-track { background:var(--tx-bg); }
::-webkit-scrollbar-thumb { background:var(--tx-b); border-radius:3px; }

/* ══════════════════════════════════════════════════════
   RESPONSIVE
   ══════════════════════════════════════════════════════ */
@media(max-width:640px){
    .tx-sep,.tx-nav-badge { display:none; }
    .container { padding:20px 12px 48px !important; }
    .panel-body { padding:16px !important; }
    .tx-logout { bottom:16px; right:16px; padding:9px 16px; font-size:.8rem; }
}
</style>

<!-- Anti-flash thème -->
<script>(function(){
    var t=localStorage.getItem('talixman-theme')||'light';
    document.documentElement.setAttribute('data-theme',t);
})();</script>

</head>
<body>

<!-- ══════════════════════════════════════════════════════
     NAVBAR — logo image seul (pas de lien texte)
     ══════════════════════════════════════════════════════ -->
<header class="tx-nav">

    <!-- Logo image uniquement -->
    <img class="tx-nav-logo"
         src="Talixman_logo.png"
         alt="Talixman"
         onerror="this.style.display='none'">

    <div class="tx-sep"></div>
    <span class="tx-nav-badge">User Management</span>

    <!-- Toggle dark / light -->
    <div class="tx-theme">
        <span class="tx-icon">☀️</span>
        <label class="tx-sw">
            <input type="checkbox" id="tx-cb">
            <div class="tx-track"></div>
            <div class="tx-thumb"></div>
        </label>
        <span class="tx-icon">🌙</span>
    </div>

</header>

<!-- ══════════════════════════════════════════════════════
     BOUTON DÉCONNEXION flottant
     Visible uniquement si l'admin est connecté
     Le lien pointe vers admin_logout.php (lien htadmin existant)
     ══════════════════════════════════════════════════════ -->
<a href="admin_logout.php" class="tx-logout" title="Se déconnecter">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
        <polyline points="16 17 21 12 16 7"/>
        <line x1="21" y1="12" x2="9" y2="12"/>
    </svg>
    Déconnexion
</a>

<!-- ══════════════════════════════════════════════════════
     JS NATIF — remplace bootstrap.min.js
     ══════════════════════════════════════════════════════ -->
<script>
document.addEventListener('DOMContentLoaded',function(){

    /* Toggle thème */
    var cb=document.getElementById('tx-cb');
    if(cb){
        var saved=localStorage.getItem('talixman-theme')||'light';
        cb.checked=(saved==='dark');
        cb.addEventListener('change',function(){
            var t=this.checked?'dark':'light';
            document.documentElement.setAttribute('data-theme',t);
            localStorage.setItem('talixman-theme',t);
        });
    }

    /* Tabs */
    document.querySelectorAll('.nav-tabs a').forEach(function(tab){
        tab.addEventListener('click',function(e){
            e.preventDefault();
            var target=this.getAttribute('href');
            if(!target) return;
            this.closest('.nav-tabs')
                .querySelectorAll('li')
                .forEach(function(li){li.classList.remove('active');});
            document.querySelectorAll('.tab-pane')
                .forEach(function(p){p.classList.remove('active','in');});
            this.parentElement.classList.add('active');
            var pane=document.querySelector(target);
            if(pane) pane.classList.add('active','in');
        });
    });

    /* Collapse */
    document.querySelectorAll('[data-toggle="collapse"]').forEach(function(btn){
        btn.addEventListener('click',function(e){
            e.preventDefault();
            var sel=this.dataset.target||this.getAttribute('href');
            var el=document.querySelector(sel);
            if(!el) return;
            var open=el.classList.contains('in');
            el.classList.toggle('in',!open);
            el.style.display=open?'none':'block';
        });
    });

    /* Alertes dismissibles */
    document.querySelectorAll('[data-dismiss="alert"]').forEach(function(btn){
        btn.addEventListener('click',function(){
            var a=this.closest('.alert');
            if(a){
                a.style.transition='opacity .3s';
                a.style.opacity='0';
                setTimeout(function(){a.remove();},300);
            }
        });
    });

    /* Confirmation suppression */
    document.querySelectorAll('[data-confirm]').forEach(function(btn){
        btn.addEventListener('click',function(e){
            if(!confirm(this.dataset.confirm||'Confirmer ?')) e.preventDefault();
        });
    });

    /* Cacher le bouton déconnexion sur la page de login */
    var logout=document.querySelector('.tx-logout');
    if(logout){
        /* Si on est sur la page de login (pas de panel admin visible), masquer */
        var isLoginPage = !document.querySelector('table') &&
                          document.querySelector('input[name="password"]') &&
                          !document.querySelector('input[name="new_password"]');
        if(isLoginPage) logout.style.display='none';
    }

});
</script>

<!-- Le contenu PHP (formulaires, tables...) est injecté ici par les autres .php -->