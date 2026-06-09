import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children: content }) => <p className="mb-2 last:mb-0">{content}</p>,
        ul: ({ children: content }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{content}</ul>,
        ol: ({ children: content }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{content}</ol>,
        li: ({ children: content }) => <li className="leading-6">{content}</li>,
        strong: ({ children: content }) => <strong className="font-semibold">{content}</strong>,
        em: ({ children: content }) => <em className="italic">{content}</em>,
        code: ({ children: content }) => (
          <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-[13px] dark:bg-gray-800/60">{content}</code>
        ),
        h1: ({ children: content }) => <h1 className="mb-2 text-[16px] font-semibold">{content}</h1>,
        h2: ({ children: content }) => <h2 className="mb-2 text-[15px] font-semibold">{content}</h2>,
        h3: ({ children: content }) => <h3 className="mb-1 text-[14px] font-semibold">{content}</h3>,
      }}
    >
      {children}
    </ReactMarkdown>
  )
}
