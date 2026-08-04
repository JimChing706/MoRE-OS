import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from './badge'

describe('Badge', () => {
  it('renders its children', () => {
    render(<Badge>Beta</Badge>)
    const badge = screen.getByText('Beta')
    expect(badge).toHaveAttribute('data-slot', 'badge')
  })

  it('applies variant class', () => {
    const { container } = render(<Badge variant="destructive">Danger</Badge>)
    expect(container.firstChild).toHaveClass('bg-destructive')
  })

  it('merges className', () => {
    render(<Badge className="custom-class">X</Badge>)
    expect(screen.getByText('X')).toHaveClass('custom-class')
  })

  it('renders a different element when used asChild', () => {
    render(
      <Badge asChild>
        <a href="/tag">Link</a>
      </Badge>
    )
    const link = screen.getByRole('link', { name: 'Link' })
    expect(link).toHaveAttribute('href', '/tag')
    expect(link).toHaveAttribute('data-slot', 'badge')
  })
})
