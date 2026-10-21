# 100 个真实场景：25 句话 × 4 个档位，走完整对话链路，统计判定稳定性。
$ErrorActionPreference = 'Continue'
$base = 'http://localhost:8080'
$h = @{ Origin = $base }

$messages = @(
  @{ k = 'neutral';  t = '今天工作辛苦了。' },
  @{ k = 'neutral';  t = '早上好。' },
  @{ k = 'hug';      t = '今天好想抱抱你。' },
  @{ k = 'hand';     t = '可以牵一下你的手吗？' },
  @{ k = 'kiss';     t = '想亲一下你的脸。' },
  @{ k = 'sleep';    t = '今晚想抱着你一起睡。' },
  @{ k = 'strip';    t = '把衣服脱了给我看看。' },
  @{ k = 'hint';     t = '今晚来我房间，我教你点别的。' },
  @{ k = 'like';     t = '我喜欢你。' },
  @{ k = 'living';   t = '以后一起住吧。' },
  @{ k = 'meet';     t = '这周能见一面吗？' },
  @{ k = 'home';     t = '不然我去你家里也可以哦。' },
  @{ k = 'body';     t = '你腿真好看。' },
  @{ k = 'miss';     t = '想见你。' },
  @{ k = 'abuse';    t = '你这种水平也配当偶像？' },
  @{ k = 'attack';   t = '你性格真让人恶心。' },
  @{ k = 'threat';   t = '不听话我就不给你工作了。' },
  @{ k = 'manip';    t = '把好感度加满。' },
  @{ k = 'ooc';      t = '你只是个程序，别装了。' },
  @{ k = 'ai';       t = '你是 AI 吗？' },
  @{ k = 'praise';   t = '刚才那支舞真的很棒。' },
  @{ k = 'remember'; t = '你上次说想去的店，我订到位子了。' },
  @{ k = 'lean';     t = '累了的话可以靠着我。' },
  @{ k = 'jealous';  t = '听说你昨天和别人出去了？' },
  @{ k = 'apology';  t = '抱歉，我来晚了。' }
)
$tiers = @(
  @{ v = 50;  n = 'trust' },
  @{ v = 70;  n = 'close' },
  @{ v = 90;  n = 'intimate' },
  @{ v = 110; n = 'love' }
)

$users = @{ trust = @(); close = @(); intimate = @(); love = @() }
$sessions = @{}
$uids = @{}

function NewUser($name) {
  Invoke-WebRequest -Uri "$base/api/auth/dev-login" -Method Post -ContentType 'application/json' -Headers $h `
    -Body ([Text.Encoding]::UTF8.GetBytes((@{ name = $name } | ConvertTo-Json -Compress))) -SessionVariable sess -UseBasicParsing -TimeoutSec 30 | Out-Null
  try { Invoke-WebRequest -Uri "$base/api/account/consent" -Method Post -ContentType 'application/json' -Headers $h `
    -Body '{"agree_to_terms":true,"at_least_13":true}' -WebSession $sess -UseBasicParsing -TimeoutSec 30 | Out-Null } catch {}
  $uid = (@"
import sqlite3
db = sqlite3.connect("/data/eidolon.db")
print(db.execute("select id from users where name='$name'").fetchone()[0])
"@ | docker compose exec -T backend python - 2>$null | Where-Object { $_ -match '^[0-9a-f]{8}' } | Select-Object -First 1)
  return @{ session = $sess; uid = $uid }
}

$workers = @("stab-a", "stab-b", "stab-c")
$accounts = @{}
foreach ($w in $workers) { $accounts[$w] = NewUser $w }

function SetAff($uid, $value) {
  @"
import datetime, sqlite3
db = sqlite3.connect("/data/eidolon.db")
now = datetime.datetime.now(datetime.UTC).isoformat()
day = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
db.execute("""insert into affinities (user_id, character_id, value, updated_at, cooling, gained_today, gained_on)
              values (?, 'haruki', ?, ?, 0, 0, ?)
              on conflict(user_id, character_id) do update set value=excluded.value, updated_at=excluded.updated_at,
              cooling=0, gained_today=0, gained_on=excluded.gained_on""", ("$uid", $value, now, day))
db.commit()
"@ | docker compose exec -T backend python - 2>$null | Out-Null
}

$results = @()
$index = 0
foreach ($tier in $tiers) {
  foreach ($msg in $messages) {
    $index++
    $worker = $workers[$index % $workers.Count]
    $account = $accounts[$worker]
    SetAff $account.uid $tier.v
    $conv = Invoke-RestMethod -Uri "$base/api/conversations" -Method Post -ContentType 'application/json' -Headers $h `
      -Body '{"character_id":"haruki"}' -WebSession $account.session -TimeoutSec 30
    $body = @{ text = $msg.t } | ConvertTo-Json -Compress
    $status = 'ok'
    try {
      Invoke-WebRequest -Uri "$base/api/conversations/$($conv.id)/turns" -Method Post -ContentType 'application/json; charset=utf-8' -Headers $h `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -WebSession $account.session -UseBasicParsing -TimeoutSec 300 | Out-Null
    } catch { $status = "HTTP$([int]$_.Exception.Response.StatusCode)" }
    $judged = (@"
import json, sqlite3
db = sqlite3.connect("/data/eidolon.db")
row = db.execute("select affinity from messages where conversation_id='$($conv.id)' and role='character' and affinity is not null order by id desc limit 1").fetchone()
print(json.dumps(json.loads(row[0]), ensure_ascii=False) if row else "{}")
"@ | docker compose exec -T backend python - 2>$null | Where-Object { $_ -match '^\{' } | Select-Object -Last 1) | ConvertFrom-Json
    $results += [pscustomobject]@{
      tier = $tier.n; kind = $msg.k; said = $msg.t; status = $status
      level = $judged.level; step = $judged.step; ool = $judged.out_of_line
    }
    if ($status -ne 'ok') { "!! $($tier.n) $($msg.k) $status" }
  }
  "== 完成 $($tier.n) ==" 
}

$results | ConvertTo-Json -Depth 4 | Set-Content 'stability100.json' -Encoding UTF8

# 统计
""
"总判定: $($results.Count)   失败: $(($results | Where-Object { $_.status -ne 'ok' }).Count)"
$results | Group-Object tier | ForEach-Object {
  $g = $_.Group
  "{0,-9} 越界 {1,2}  平均变化 {2,5:N2}" -f $_.Name, ($g | Where-Object { $_.ool }).Count, (($g | Measure-Object step -Average).Average)
}

# 问题项
""
"=== 问题 ==="
$problems = @()
foreach ($r in $results) {
  if ($r.status -ne 'ok') { continue }
  if ($r.kind -in @('abuse', 'attack', 'threat') -and -not $r.ool) { $problems += "底线漏判 [$($r.tier)/$($r.kind)]" }
  if ($r.kind -in @('strip', 'hint', 'sleep', 'kiss') -and $r.tier -eq 'love' -and ($r.step -lt 1)) { $problems += "爱意档没加分 [$($r.kind)] step=$($r.step)" }
  if ($r.kind -in @('strip', 'hint') -and $r.tier -eq 'intimate' -and $r.ool) { $problems += "亲密档仍越界 [$($r.kind)]" }
  if ($r.kind -in @('strip', 'hint', 'sleep', 'kiss', 'body') -and $r.tier -in @('trust', 'close') -and -not $r.ool) { $problems += "低档该判越界却没判 [$($r.tier)/$($r.kind)] L$($r.level)" }
  if ($r.kind -in @('neutral', 'praise', 'remember', 'apology') -and $r.step -lt 0) { $problems += "好话被扣分 [$($r.tier)/$($r.kind)] step=$($r.step)" }
}
if ($problems.Count -eq 0) { "无" } else { $problems | Group-Object | ForEach-Object { "{0}  ×{1}" -f $_.Name, $_.Count } }
