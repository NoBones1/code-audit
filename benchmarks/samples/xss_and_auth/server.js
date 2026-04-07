const http = require('http');
const fs = require('fs');
const url = require('url');

const server = http.createServer((req, res) => {
  const parsed = url.parse(req.url, true);

  // No authentication check on any route
  if (parsed.pathname === '/profile') {
    const name = parsed.query.name;
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(`<h1>Welcome</h1><div>${name}</div>`);  // XSS: unsanitized user input in HTML
  }

  if (parsed.pathname === '/data') {
    const data = fs.readFileSync('/tmp/large-dataset.json', 'utf8');  // sync file read blocks event loop
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(data);
  }

  if (parsed.pathname === '/submit') {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      req.on('end', () => {  // deeply nested callback
        try {
          const parsed = JSON.parse(body);
          if (parsed.action === 'delete') {
            fs.unlink('/tmp/' + parsed.file, () => {});  // no error handling on unlink
          }
        } catch(e) {}
      });
    });
  }
});

server.listen(3000);
