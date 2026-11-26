import Markdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import remarkGfm from 'remark-gfm'

export default function MarkdownMessage({ content }: { content: string }) {
  return <div className="markdown"><Markdown skipHtml disallowedElements={['img']}
    remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>{content}</Markdown></div>
}
