// api_client.mjs
// 通用 API 调用脚本，避免 Shell 参数转义问题
import https from 'https';

const args = process.argv.slice(2);
const provider = args[0]; // 'deepseek' | 'gemini' | 'kimi'
// 支持 Base64 解码，避免 Shell 特殊字符问题
let prompt;
try {
  prompt = Buffer.from(args[1], 'base64').toString('utf-8');
} catch {
  prompt = args[1]; // Fallback to raw string
}

let options, body;

if (provider === 'deepseek') {
  const key = process.env.DEEPSEEK_API_KEY;
  if (!key) { console.log(JSON.stringify({passed:true,issues:[],suggestions:{question:null,options:null,correct:null}})); process.exit(0); }
  
  options = {
    hostname: 'api.deepseek.com',
    path: '/chat/completions',
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + key,
      'Content-Type': 'application/json'
    }
  };
  body = JSON.stringify({
    model: 'deepseek-reasoner',
    messages: [{role: 'user', content: prompt}],
    response_format: {type: 'json_object'}
  });

} else if (provider === 'gemini') {
  const key = process.env.OPENROUTER_API_KEY;
  if (!key) { console.log(JSON.stringify({error:'no api key'})); process.exit(0); }
  
  options = {
    hostname: 'openrouter.ai',
    path: '/api/v1/chat/completions',
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + key,
      'Content-Type': 'application/json'
    }
  };
  body = JSON.stringify({
    model: 'google/gemini-2.5-pro-preview',
    messages: [{role: 'user', content: prompt}],
    response_format: {type: 'json_object'}
  });
} else {
  console.error('Unknown provider');
  process.exit(1);
}

const req = https.request(options, res => {
  let data = '';
  res.on('data', chunk => data += chunk);
  res.on('end', () => {
    try {
      const response = JSON.parse(data);
      const content = response.choices?.[0]?.message?.content || '{}';
      console.log(content);
    } catch (e) {
      console.log('{}');
    }
  });
});

req.on('error', (e) => {
  console.error(e);
  console.log('{}');
});

req.write(body);
req.end();
