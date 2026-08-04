import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Button } from './button'

describe('Button', () => {
  it('renders its label', () => {
    render(<Button>Submit</Button>)
    expect(screen.getByRole('button', { name: 'Submit' })).toBeInTheDocument()
  })

  it('applies default variant and size data attributes', () => {
    render(<Button>Go</Button>)
    const button = screen.getByRole('button', { name: 'Go' })
    expect(button).toHaveAttribute('data-slot', 'button')
    expect(button).toHaveAttribute('data-variant', 'default')
    expect(button).toHaveAttribute('data-size', 'default')
  })

  it('applies explicit variant and size', () => {
    render(<Button variant="destructive" size="sm">Delete</Button>)
    const button = screen.getByRole('button', { name: 'Delete' })
    expect(button).toHaveAttribute('data-variant', 'destructive')
    expect(button).toHaveAttribute('data-size', 'sm')
  })

  it('merges className with variant classes', () => {
    render(<Button className="custom-class">Styled</Button>)
    expect(screen.getByRole('button', { name: 'Styled' })).toHaveClass('custom-class')
  })

  it('fires onClick and respects disabled state', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Click</Button>)
    fireEvent.click(screen.getByRole('button', { name: 'Click' }))
    expect(onClick).toHaveBeenCalledTimes(1)

    render(<Button disabled onClick={onClick}>Locked</Button>)
    const locked = screen.getByRole('button', { name: 'Locked' })
    expect(locked).toBeDisabled()
    fireEvent.click(locked)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('renders a different element when used asChild', () => {
    render(
      <Button asChild>
        <a href="/target">Link</a>
      </Button>
    )
    const link = screen.getByRole('link', { name: 'Link' })
    expect(link).toHaveAttribute('href', '/target')
    expect(link).toHaveAttribute('data-slot', 'button')
  })
})
