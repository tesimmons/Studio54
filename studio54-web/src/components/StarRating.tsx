import { useState } from 'react'
import { S54 } from '../assets/graphics'

interface StarRatingProps {
  rating: number | null
  onChange?: (rating: number | null) => void
  size?: 'sm' | 'md'
}

export default function StarRating({ rating, onChange, size = 'sm' }: StarRatingProps) {
  const [hoverRating, setHoverRating] = useState<number | null>(null)

  const isInteractive = !!onChange
  const displayRating = hoverRating ?? rating ?? 0
  const starSize = size === 'sm' ? 'w-4 h-4' : 'w-5 h-5'

  const handleClick = (star: number) => {
    if (!onChange) return
    onChange(star === rating ? null : star)
  }

  return (
    <div
      className="inline-flex items-center gap-0.5"
      onMouseLeave={() => isInteractive && setHoverRating(null)}
    >
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          disabled={!isInteractive}
          className={`${isInteractive ? 'cursor-pointer hover:scale-110' : 'cursor-default'} transition-transform disabled:opacity-100`}
          onClick={(e) => { e.stopPropagation(); handleClick(star) }}
          onMouseEnter={() => isInteractive && setHoverRating(star)}
        >
          <img
            src={star <= displayRating ? S54.starSelected : S54.starUnselected}
            alt={star <= displayRating ? 'Filled star' : 'Empty star'}
            className={`${starSize} object-contain`}
          />
        </button>
      ))}
    </div>
  )
}
